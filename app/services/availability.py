"""Which rounds of an event a player cannot play.

A row is an answer, and no row is no answer, so clearing an answer deletes the
row. The player and their captain write the same row and the last write wins.
"""

from collections.abc import Sequence
from datetime import UTC, date, datetime

from sqlalchemy import ColumnExpressionArgument, delete, select
from sqlalchemy.orm import Session as OrmSession
from sqlmodel import col

from app.core.checkin_hint import blocked_rounds, round_window
from app.core.db import Session
from app.core.exceptions import ApiError, BadRequestError, NotFoundError
from app.models.base import ident
from app.models.relationships import DBEventRound, SeasonRoundPublic, round_row
from app.models.round_availability import (
    DBRoundAvailability,
    RoundAvailabilityPublic,
)
from app.models.season import Season
from app.models.types import utcnow
from app.models.user import User
from app.models.user_team_season import DBUserTeamSeason
from app.services.events import checkin_window

NO_SCHEDULING = "This event does not use availability."


def now() -> datetime:
    """The instant the check-in reads; today is its UTC date."""
    return datetime.now(UTC)


def today() -> date:
    return now().date()


class AvailabilityService:
    def season_weeks(self, season_id: int) -> int:
        with Session.begin() as session:
            return _season(session, season_id).round_count or 0

    def season_rounds(self, season_id: int) -> list[SeasonRoundPublic]:
        """The rounds the dashboard asks about, with their date windows."""
        with Session.begin() as session:
            season = _season(session, season_id)
            return [SeasonRoundPublic.from_row(row) for row in season.rounds]

    def for_user(self, user_id: int, season_id: int) -> list[RoundAvailabilityPublic]:
        with Session.begin() as session:
            return _derive(
                session,
                session.get(Season, season_id),
                [user_id],
                _rows(
                    session,
                    col(DBRoundAvailability.user_id) == user_id,
                    col(DBRoundAvailability.season_id) == season_id,
                ),
            )

    def for_team(self, team_id: int, season_id: int) -> list[RoundAvailabilityPublic]:
        """The answers of the players the team holds that season."""
        with Session.begin() as session:
            return team_rows(session, team_id, season_id)

    def on_roster(self, team_id: int, season_id: int, user_id: int) -> bool:
        with Session.begin() as session:
            key = (user_id, team_id, season_id)
            return session.get(DBUserTeamSeason, key) is not None

    def set(
        self,
        user_id: int,
        season_id: int,
        playday: int,
        available: bool | None,
        set_by_user_id: int,
    ) -> list[RoundAvailabilityPublic]:
        """Write one round's answer, or clear it, and answer the player's season.

        Every writer comes through here, so a season without scheduling refuses
        the player, the captain and the Discord button alike. A player answers
        only inside the check-in window; a captain or an admin at any time.
        """
        with Session.begin() as session:
            season = _season(session, season_id)
            if not season.scheduling_enabled:
                raise ApiError(
                    403, {"error": "scheduling_disabled", "message": NO_SCHEDULING}
                )
            weeks = season.round_count or 0
            if not 1 <= playday <= weeks:
                raise BadRequestError(f"playday must be between 1 and {weeks}")
            if set_by_user_id == user_id:
                _checkin_window(season, playday)
            if available is None:
                row = session.get(DBRoundAvailability, (user_id, season_id, playday))
                if row:
                    session.delete(row)
            else:
                round_ = round_row(session, season_id, playday)
                session.merge(
                    DBRoundAvailability(
                        user_id=user_id,
                        season_id=season_id,
                        playday=playday,
                        round_id=round_.id if round_ else None,
                        available=available,
                        set_by_user_id=set_by_user_id,
                        answered_at=utcnow(),
                    )
                )
            session.flush()
            return _season_rows(session, season, user_id)

    def set_all(
        self,
        user_id: int,
        season_id: int,
        available: bool | None,
        set_by_user_id: int,
    ) -> list[RoundAvailabilityPublic]:
        """Answer every round of the event that has not ended, or clear them all.

        One delete and one insert write the lot, so the rounds move together.
        A player writing for themselves meets the same window rule per round as
        a single answer, which early check-in opens for every round left.
        """
        with Session.begin() as session:
            season = _season(session, season_id)
            if not season.scheduling_enabled:
                raise ApiError(
                    403, {"error": "scheduling_disabled", "message": NO_SCHEDULING}
                )
            rounds = [row for row in season.rounds if not _ended(season, row)]
            if set_by_user_id == user_id:
                for row in rounds:
                    _checkin_window(season, row.number)
            session.execute(
                delete(DBRoundAvailability).where(
                    col(DBRoundAvailability.user_id) == user_id,
                    col(DBRoundAvailability.season_id) == season_id,
                    col(DBRoundAvailability.playday).in_(
                        [row.number for row in rounds]
                    ),
                )
            )
            if available is not None:
                session.add_all(
                    [
                        DBRoundAvailability(
                            user_id=user_id,
                            season_id=season_id,
                            playday=row.number,
                            round_id=row.id,
                            available=available,
                            set_by_user_id=set_by_user_id,
                            answered_at=utcnow(),
                        )
                        for row in rounds
                    ]
                )
            session.flush()
            return _season_rows(session, season, user_id)


def team_rows(
    session: OrmSession, team_id: int, season_id: int
) -> list[RoundAvailabilityPublic]:
    """The stored and derived answers of the players the team holds that season."""
    roster = list(
        session.scalars(
            select(col(DBUserTeamSeason.user_id)).where(
                col(DBUserTeamSeason.team_id) == team_id,
                col(DBUserTeamSeason.season_id) == season_id,
            )
        )
    )
    return _derive(
        session,
        session.get(Season, season_id),
        roster,
        _rows(
            session,
            col(DBRoundAvailability.season_id) == season_id,
            col(DBRoundAvailability.user_id).in_(roster),
        ),
    )


def out_rounds(
    session: OrmSession, team_id: int, season_id: int
) -> dict[int, list[int]]:
    """The rounds each player of the event team sits out, by player id.

    A stored "no" and a derived out-on-blocked-times round read the same here,
    so the answer says which rounds, never why and never who wrote them.
    """
    out: dict[int, list[int]] = {}
    for row in team_rows(session, team_id, season_id):
        if not row.available:
            out.setdefault(row.user_id, []).append(row.playday)
    return out


def _checkin_window(season: Season, playday: int) -> None:
    """Refuse a player before the round's check-in opens and after it ends."""
    # An event that takes no check-in, or a blank window, keeps every round open
    if not season.checkin_enabled:
        return
    row = next((r for r in season.rounds if r.number == playday), None)
    window = checkin_window(season, row) if row else None
    if window is None or row is None:
        return
    opens, closes = window
    # Early check-in takes an answer for every round of the event that is left
    if not season.early_checkin and today() < opens:
        raise _closed(f"Check-in for round {playday} opens on {opens.day} {opens:%b}.")
    if closes and _ended(season, row):
        raise _closed(f"Round {playday} is over.")


def _ended(season: Season, row: DBEventRound) -> bool:
    """Whether the round is over: past midnight after its last day, event zone.

    A round nobody dated never ends, so it stays open to an answer.
    """
    if row.start_date is None:
        return False
    window = round_window(season, row)
    return window is not None and now() >= window[1]


def _closed(message: str) -> ApiError:
    return ApiError(403, {"error": "checkin_closed", "message": message})


def _season(session: OrmSession, season_id: int) -> Season:
    season = session.get(Season, season_id)
    if not season:
        raise NotFoundError(f"Season not found by Id: {season_id}")
    return season


def _season_rows(
    session: OrmSession, season: Season, user_id: int
) -> list[RoundAvailabilityPublic]:
    """One player's rows for that event: what every availability write answers."""
    return _derive(
        session,
        season,
        [user_id],
        _rows(
            session,
            col(DBRoundAvailability.user_id) == user_id,
            col(DBRoundAvailability.season_id) == ident(season),
        ),
    )


def _derive(
    session: OrmSession,
    season: Season | None,
    user_ids: Sequence[int],
    rows: list[RoundAvailabilityPublic],
) -> list[RoundAvailabilityPublic]:
    """The stored answers, plus a derived row where blocks cover a whole round.

    A stored answer always wins, so a derived row stands only where none does.
    """
    if season is None or not user_ids:
        return rows
    answered = {(row.user_id, row.playday) for row in rows}
    derived = [
        RoundAvailabilityPublic.derived(user_id, playday)
        for user_id, playday in blocked_rounds(session, season, user_ids, season.rounds)
        if (user_id, playday) not in answered
    ]
    if not derived:
        return rows
    return sorted(rows + derived, key=lambda row: (row.user_id, row.playday))


def _rows(
    session: OrmSession, *where: ColumnExpressionArgument[bool]
) -> list[RoundAvailabilityPublic]:
    """The rows the filter keeps, each carrying the name of its last writer."""
    rows = session.execute(
        select(DBRoundAvailability, col(User.name))
        .join(User, col(User.id) == col(DBRoundAvailability.set_by_user_id))
        .where(*where)
        .order_by(
            col(DBRoundAvailability.user_id),
            col(DBRoundAvailability.playday),
        )
    ).all()
    return [RoundAvailabilityPublic.from_row(row, name) for row, name in rows]
