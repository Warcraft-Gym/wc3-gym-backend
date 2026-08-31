"""Which weeks of a season a player cannot play.

A row is an answer, and no row is no answer, so clearing an answer deletes the
row. The player and his captain write the same row and the last write wins.
"""

from sqlalchemy import ColumnExpressionArgument, select
from sqlalchemy.orm import Session as OrmSession
from sqlmodel import col

from app.core.db import Session
from app.core.exceptions import BadRequestError, NotFoundError
from app.models.season import Season
from app.models.user import User
from app.models.user_season_availability import (
    DBUserSeasonAvailability,
    UserSeasonAvailabilityPublic,
)
from app.models.user_team_season import DBUserTeamSeason


class AvailabilityService:
    def season_weeks(self, season_id: int) -> int:
        with Session.begin() as session:
            return _weeks(session, season_id)

    def for_user(
        self, user_id: int, season_id: int
    ) -> list[UserSeasonAvailabilityPublic]:
        with Session.begin() as session:
            return _rows(
                session,
                col(DBUserSeasonAvailability.user_id) == user_id,
                col(DBUserSeasonAvailability.season_id) == season_id,
            )

    def for_team(
        self, team_id: int, season_id: int
    ) -> list[UserSeasonAvailabilityPublic]:
        """The answers of the players the team holds that season."""
        with Session.begin() as session:
            roster = select(col(DBUserTeamSeason.user_id)).where(
                col(DBUserTeamSeason.team_id) == team_id,
                col(DBUserTeamSeason.season_id) == season_id,
            )
            return _rows(
                session,
                col(DBUserSeasonAvailability.season_id) == season_id,
                col(DBUserSeasonAvailability.user_id).in_(roster),
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
    ) -> list[UserSeasonAvailabilityPublic]:
        """Write one week's answer, or clear it, and answer the player's season."""
        with Session.begin() as session:
            weeks = _weeks(session, season_id)
            if not 1 <= playday <= weeks:
                raise BadRequestError(f"playday must be between 1 and {weeks}")
            if available is None:
                row = session.get(
                    DBUserSeasonAvailability, (user_id, season_id, playday)
                )
                if row:
                    session.delete(row)
            else:
                session.merge(
                    DBUserSeasonAvailability(
                        user_id=user_id,
                        season_id=season_id,
                        playday=playday,
                        available=available,
                        set_by_user_id=set_by_user_id,
                    )
                )
            session.flush()
            return _rows(
                session,
                col(DBUserSeasonAvailability.user_id) == user_id,
                col(DBUserSeasonAvailability.season_id) == season_id,
            )


def _weeks(session: OrmSession, season_id: int) -> int:
    season = session.get(Season, season_id)
    if not season:
        raise NotFoundError(f"Season not found by Id: {season_id}")
    return season.number_weeks


def _rows(
    session: OrmSession, *where: ColumnExpressionArgument[bool]
) -> list[UserSeasonAvailabilityPublic]:
    """The rows the filter keeps, each carrying the name of its last writer."""
    rows = session.execute(
        select(DBUserSeasonAvailability, col(User.name))
        .join(User, col(User.id) == col(DBUserSeasonAvailability.set_by_user_id))
        .where(*where)
        .order_by(
            col(DBUserSeasonAvailability.user_id),
            col(DBUserSeasonAvailability.playday),
        )
    ).all()
    return [UserSeasonAvailabilityPublic.from_row(row, name) for row, name in rows]
