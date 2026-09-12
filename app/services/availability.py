"""Which rounds of an event a player cannot play.

A row is an answer, and no row is no answer, so clearing an answer deletes the
row. The player and their captain write the same row and the last write wins.
"""

from sqlalchemy import ColumnExpressionArgument, select
from sqlalchemy.orm import Session as OrmSession
from sqlmodel import col

from app.core.db import Session
from app.core.exceptions import ApiError, BadRequestError, NotFoundError
from app.models.base import ident
from app.models.relationships import SeasonRoundPublic, round_row
from app.models.round_availability import (
    DBRoundAvailability,
    RoundAvailabilityPublic,
)
from app.models.season import Season
from app.models.user import User
from app.models.user_team_season import DBUserTeamSeason

NO_SCHEDULING = "This event does not use availability."


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
            return _rows(
                session,
                col(DBRoundAvailability.user_id) == user_id,
                col(DBRoundAvailability.season_id) == season_id,
            )

    def for_team(self, team_id: int, season_id: int) -> list[RoundAvailabilityPublic]:
        """The answers of the players the team holds that season."""
        with Session.begin() as session:
            roster = select(col(DBUserTeamSeason.user_id)).where(
                col(DBUserTeamSeason.team_id) == team_id,
                col(DBUserTeamSeason.season_id) == season_id,
            )
            return _rows(
                session,
                col(DBRoundAvailability.season_id) == season_id,
                col(DBRoundAvailability.user_id).in_(roster),
            )

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
        the player, the captain and the Discord button alike.
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
            round_ = round_row(session, season_id, playday)
            if round_ is None:
                raise NotFoundError(f"Round not found by number: {playday}")
            if available is None:
                row = session.get(DBRoundAvailability, (user_id, ident(round_)))
                if row:
                    session.delete(row)
            else:
                session.merge(
                    DBRoundAvailability(
                        user_id=user_id,
                        season_id=season_id,
                        playday=playday,
                        round_id=ident(round_),
                        available=available,
                        set_by_user_id=set_by_user_id,
                    )
                )
            session.flush()
            return _rows(
                session,
                col(DBRoundAvailability.user_id) == user_id,
                col(DBRoundAvailability.season_id) == season_id,
            )


def _season(session: OrmSession, season_id: int) -> Season:
    season = session.get(Season, season_id)
    if not season:
        raise NotFoundError(f"Season not found by Id: {season_id}")
    return season


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
