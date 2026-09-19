"""A player's own soft blocks, and the free time two players share.

The routes pass the signed-in player's id, so a player writes only their own
rows, and a row of anyone else answers 403. Nothing here writes
round_availability: a block is a hint, never the round answer.
"""

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession
from sqlmodel import col

from app.core import free_time
from app.core.checkin_hint import blocked, zone_of
from app.core.checkin_hint import round_window as round_instants
from app.core.db import Session
from app.core.exceptions import ApiError, BadRequestError, NotFoundError
from app.models.relationships import DBEventRound, round_row
from app.models.season import Season
from app.models.series import Series
from app.models.user import User
from app.models.user_block import (
    FreeRange,
    FreeTimePublic,
    PairFreeTimePublic,
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
from app.models.user_team_season import DBUserTeamSeason
from app.services.availability import NO_SCHEDULING
from app.services.series_rules import series_event, series_round

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
        seats: set[tuple[int, int]],
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
            event = series_event(session, series)
            if event is None:
                raise NotFoundError("season_not_found")
            match = series.match
            teams = (
                {
                    (match.team1_id, match.season_id),
                    (match.team2_id, match.season_id),
                }
                if match is not None
                else set()
            )
            players = (series.player1_id, series.player2_id)
            if not (admin or user_id in players or teams & seats):
                raise ApiError(403, {"error": "not_authorized_for_this_series"})
            if not event.scheduling_enabled:
                raise ApiError(
                    403, {"error": "scheduling_disabled", "message": NO_SCHEDULING}
                )
            start, end = _window(series_round(session, series), event, start, end)
            side1, side2 = series.player1_id, series.player2_id
            if side1 is None or side2 is None:
                raise BadRequestError("The series has no sides to compare yet")
            ranges = shared_free(session, side1, side2, start, end)
        return FreeTimePublic(
            start=start,
            end=end,
            hours=free_hours(ranges),
            ranges=[FreeRange(start=lo, end=hi) for lo, hi in ranges],
        )

    def pair_free_time(
        self,
        event_id: int,
        playday: int,
        user_a: int,
        user_b: int,
        *,
        admin: bool,
        seats: set[tuple[int, int]],
    ) -> PairFreeTimePublic:
        """The hours two players share across a round, before a series pairs them.

        Both players hold a seat in that event, and a captain reads a pair that
        holds one of the players their own team fields; an admin passes the
        captain rule only. It answers a count only, so neither the blocks nor
        the ranges reach the caller.
        """
        with Session.begin() as session:
            round_ = round_row(session, event_id, playday)
            if round_ is None:
                raise NotFoundError("round_not_found")
            event = session.get(Season, event_id)
            if event is None:
                raise NotFoundError("season_not_found")
            if not _pair_seated(
                session, event_id, seats, (user_a, user_b), admin=admin
            ):
                raise ApiError(403, {"error": "not_authorized_for_this_pair"})
            if not event.scheduling_enabled:
                raise ApiError(
                    403, {"error": "scheduling_disabled", "message": NO_SCHEDULING}
                )
            start, end = _window(round_, event, None, None)
            ranges = shared_free(session, user_a, user_b, start, end)
        return PairFreeTimePublic(hours=free_hours(ranges))


def shared_free(
    session: OrmSession,
    user_a: int,
    user_b: int,
    start: datetime,
    end: datetime,
    spans: Mapping[int, list[free_time.Interval]] | None = None,
) -> list[free_time.Interval]:
    """The UTC ranges both players have open inside [start, end).

    A caller that answers many pairs reads the blocks once per player and
    passes them in spans, so a player found in spans costs no statement.
    """
    spans = spans or {}
    both = [
        spans[side]
        if side in spans
        else blocked(session, side, start, end, zone_of(session, side))
        for side in (user_a, user_b)
    ]
    return free_time.free(start, end, *both)


def free_hours(ranges: list[free_time.Interval]) -> float:
    """The hours a set of ranges covers, the one figure a pair read answers."""
    return sum((hi - lo).total_seconds() for lo, hi in ranges) / 3600


def round_window(row: DBEventRound | None, event: Season) -> tuple[datetime, datetime]:
    """The instants one round runs between, else the event's; over 31 days it refuses."""
    return _window(row, event, None, None)


def _pair_seated(
    session: OrmSession,
    event_id: int,
    seats: set[tuple[int, int]],
    users: tuple[int, ...],
    *,
    admin: bool,
) -> bool:
    """Whether the caller may read this pair: every player holds a seat in this
    event, and, unless the caller is an admin, a captain's seat of this event
    fields one of them. One statement answers both, so the rows load once."""
    rows = session.scalars(
        select(DBUserTeamSeason).where(
            col(DBUserTeamSeason.season_id) == event_id,
            col(DBUserTeamSeason.user_id).in_(users),
        )
    ).all()
    if {row.user_id for row in rows} != set(users):
        return False
    teams = {team for team, season in seats if season == event_id}
    return admin or any(row.team_id in teams for row in rows)


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
            raise BadRequestError("The last day must not be before the first day")
        return
    if row.start_local.tzinfo or row.end_local.tzinfo:
        raise BadRequestError("Times must be clock times without an offset")
    if row.start_local == row.end_local:
        raise BadRequestError("A block must end at a different time than it starts")


def _utc(value: datetime) -> datetime:
    return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)


def _window(
    row: DBEventRound | None,
    event: Season,
    start: datetime | None,
    end: datetime | None,
) -> tuple[datetime, datetime]:
    """The window asked for, else the round's days, else the event's, midnight
    to midnight in the event's zone. The caller resolves the round: a series
    generated into a bracket has no fixture, so its round comes through its own
    round_id."""
    if start is None and end is None:
        window = round_instants(event, row)
        if window is None:
            raise BadRequestError("The round has no dates; pass start and end")
        start, end = window
    if start is None or end is None:
        raise BadRequestError("Pass both start and end, or neither")
    start, end = _utc(start), _utc(end)
    if not start < end <= start + MAX_WINDOW:
        raise BadRequestError("end must come after start, by 31 days at most")
    return start, end
