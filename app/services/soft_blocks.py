"""A player's own soft blocks, and the free time the two players of a series share.

The routes pass the signed-in player's id, so a player writes only their own
rows, and a row of anyone else answers 403. Nothing here writes
user_season_availability: a block is a hint, never the round answer.
"""

from datetime import UTC, date, datetime, time, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession
from sqlmodel import col

from app.core import free_time
from app.core.db import Session
from app.core.exceptions import ApiError, BadRequestError, NotFoundError
from app.models.match import Match
from app.models.relationships import DBSeasonRound
from app.models.season import Season
from app.models.series import Series
from app.models.user import User
from app.models.user_block import (
    FreeRange,
    FreeTimePublic,
    SoftBlocksPublic,
    UserBlock,
    UserBlockCreate,
    UserBlockPublic,
    UserBlockUpdate,
    UserBusy,
    UserBusyCreate,
    UserBusyPublic,
    UserBusyUpdate,
)
from app.services.availability import NO_SCHEDULING

# The longest window the free-time read resolves
MAX_WINDOW = timedelta(days=31)


class SoftBlockService:
    def for_user(self, user_id: int) -> SoftBlocksPublic:
        with Session.begin() as session:
            blocks = session.scalars(
                select(UserBlock)
                .where(col(UserBlock.user_id) == user_id)
                .order_by(col(UserBlock.id))
            )
            busy = session.scalars(
                select(UserBusy)
                .where(col(UserBusy.user_id) == user_id)
                .order_by(col(UserBusy.first_day), col(UserBusy.id))
            )
            return SoftBlocksPublic(
                repeating=[UserBlockPublic.model_validate(row) for row in blocks],
                busy=[UserBusyPublic.model_validate(row) for row in busy],
            )

    def add_block(self, user_id: int, data: UserBlockCreate) -> UserBlockPublic:
        with Session.begin() as session:
            row = _add(session, UserBlock(user_id=user_id, **data.model_dump()))
            return UserBlockPublic.model_validate(row)

    def update_block(
        self, user_id: int, block_id: int, data: UserBlockUpdate
    ) -> UserBlockPublic:
        with Session.begin() as session:
            row = _update(session, _own(session, UserBlock, user_id, block_id), data)
            return UserBlockPublic.model_validate(row)

    def delete_block(self, user_id: int, block_id: int) -> None:
        with Session.begin() as session:
            session.delete(_own(session, UserBlock, user_id, block_id))

    def add_busy(self, user_id: int, data: UserBusyCreate) -> UserBusyPublic:
        with Session.begin() as session:
            row = _add(session, UserBusy(user_id=user_id, **data.model_dump()))
            return UserBusyPublic.model_validate(row)

    def update_busy(
        self, user_id: int, busy_id: int, data: UserBusyUpdate
    ) -> UserBusyPublic:
        with Session.begin() as session:
            row = _update(session, _own(session, UserBusy, user_id, busy_id), data)
            return UserBusyPublic.model_validate(row)

    def delete_busy(self, user_id: int, busy_id: int) -> None:
        with Session.begin() as session:
            session.delete(_own(session, UserBusy, user_id, busy_id))

    def free_time(
        self,
        series_id: int,
        *,
        admin: bool,
        user_id: int | None,
        seat: tuple[int, int] | None,
        start: datetime | None,
        end: datetime | None,
    ) -> FreeTimePublic:
        """The hours both players have free, for a player of the series, a
        captain of either team that season, or an admin.

        It answers ranges and a sum only, never whose block is whose.
        """
        with Session.begin() as session:
            series = session.get(Series, series_id)
            if series is None:
                raise NotFoundError("series_not_found")
            match = series.match
            season = session.get(Season, match.season_id)
            if season is None:
                raise NotFoundError("season_not_found")
            teams = {
                (match.team1_id, match.season_id),
                (match.team2_id, match.season_id),
            }
            players = (series.player1_id, series.player2_id)
            if not (admin or user_id in players or seat in teams):
                raise ApiError(403, {"error": "not_authorized_for_this_series"})
            if not season.scheduling_enabled:
                raise ApiError(
                    403, {"error": "scheduling_disabled", "message": NO_SCHEDULING}
                )
            start, end = _window(session, match, start, end)
            spans = [_blocked(session, player, start, end) for player in players]
        ranges = free_time.free(start, end, *spans)
        seconds = sum((hi - lo).total_seconds() for lo, hi in ranges)
        return FreeTimePublic(
            start=start,
            end=end,
            hours=seconds / 3600,
            ranges=[FreeRange(start=lo, end=hi) for lo, hi in ranges],
        )


def _add[T: (UserBlock, UserBusy)](session: OrmSession, row: T) -> T:
    """Store a new row; its times mean nothing until the player has a zone."""
    user = session.get(User, row.user_id)
    if user is None:
        raise NotFoundError("player_not_found")
    if not user.timezone:
        raise BadRequestError("Set your timezone before you add a block")
    _check(row)
    session.add(row)
    session.flush()
    return row


def _own[T: (UserBlock, UserBusy)](
    session: OrmSession, table: type[T], user_id: int, row_id: int
) -> T:
    row = session.get(table, row_id)
    if row is None:
        raise NotFoundError(f"No block by id {row_id}")
    if row.user_id != user_id:
        raise ApiError(
            403,
            {"error": "unauthorized", "message": "You can only change your own blocks"},
        )
    return row


def _update[T: (UserBlock, UserBusy)](
    session: OrmSession, row: T, data: UserBlockUpdate | UserBusyUpdate
) -> T:
    """Apply the fields sent; only the label may be cleared."""
    patch: dict[str, Any] = data.model_dump(exclude_unset=True)
    cleared = sorted(
        key for key, value in patch.items() if value is None and key != "label"
    )
    if cleared:
        raise BadRequestError(f"{', '.join(cleared)} cannot be null")
    row.sqlmodel_update(patch)
    _check(row)
    session.flush()
    return row


def _check(row: UserBlock | UserBusy) -> None:
    if isinstance(row, UserBusy):
        if row.last_day < row.first_day:
            raise BadRequestError("last_day must not be before first_day")
        return
    if row.start_local.tzinfo or row.end_local.tzinfo:
        raise BadRequestError("Local times carry no offset")
    if row.start_local == row.end_local:
        raise BadRequestError("A block must end at a different time than it starts")


def _utc(value: datetime) -> datetime:
    return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)


def _midnight(day: date) -> datetime:
    return datetime.combine(day, time(), tzinfo=UTC)


def _window(
    session: OrmSession, match: Match, start: datetime | None, end: datetime | None
) -> tuple[datetime, datetime]:
    """The window asked for, or else the round's dates as whole UTC days."""
    if start is None and end is None:
        row = session.get(DBSeasonRound, (match.season_id, match.playday))
        if row is None or row.start_date is None:
            raise BadRequestError("The round has no dates; pass start and end")
        start = _midnight(row.start_date)
        end = _midnight((row.end_date or row.start_date) + timedelta(days=1))
    if start is None or end is None:
        raise BadRequestError("Pass both start and end, or neither")
    start, end = _utc(start), _utc(end)
    if not start < end <= start + MAX_WINDOW:
        raise BadRequestError("end must come after start, by 31 days at most")
    return start, end


def _blocked(
    session: OrmSession, user_id: int, start: datetime, end: datetime
) -> list[free_time.Interval]:
    zone = session.scalar(select(col(User.timezone)).where(col(User.id) == user_id))
    blocks = session.scalars(select(UserBlock).where(col(UserBlock.user_id) == user_id))
    # A local last day can sit a calendar day behind the UTC window start
    busy = session.scalars(
        select(UserBusy).where(
            col(UserBusy.user_id) == user_id,
            col(UserBusy.last_day) >= start.date() - timedelta(days=1),
        )
    )
    return free_time.blocked(zone, blocks, busy, start, end)
