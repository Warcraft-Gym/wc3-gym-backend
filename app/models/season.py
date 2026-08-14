from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import String
from sqlalchemy.orm import Mapped, Session, mapped_column, relationship

from app.models.base import DBModel
from app.models.map import DBMap
from app.models.relationships import DBMapSeason, DBTeamSeason, DBUserSeasonSignup
from app.models.team import DBTeam
from app.models.user import DBUser

if TYPE_CHECKING:
    from app.models.relationships import DBUserTeamSeason


class DBSeason(DBModel):
    __tablename__ = "seasons"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(50))
    number_weeks: Mapped[int] = mapped_column()
    series_per_week: Mapped[int] = mapped_column()
    pick_ban: Mapped[str | None] = mapped_column(String(100))
    start_date: Mapped[date | None] = mapped_column()
    end_date: Mapped[date | None] = mapped_column()
    user_teams: Mapped[list["DBUserTeamSeason"]] = relationship(
        back_populates="season", cascade="all, delete"
    )
    teams: Mapped[list["DBTeamSeason"]] = relationship(
        back_populates="season", cascade="all, delete"
    )
    maps: Mapped[list["DBMapSeason"]] = relationship(
        back_populates="season", cascade="all, delete"
    )
    signup_users: Mapped[list["DBUserSeasonSignup"]] = relationship(
        back_populates="season", cascade="all, delete"
    )
    discordRole: Mapped[str | None] = mapped_column(String(50))

    def to_dict(self):
        return {
            column.name: getattr(self, column.name) for column in self.__table__.columns
        }

    @classmethod
    def addTeams(cls, session: Session, obj_id, team_ids):
        season = session.get(cls, obj_id)
        if not season:
            raise Exception(f"Season not found by id: {obj_id}")
        for team_id in team_ids:
            team = session.get(DBTeam, team_id)
            if not team:
                raise Exception(f"Team not found by id: {team_id}")
            already_exists = (
                session.get(DBTeamSeason, {"season_id": obj_id, "team_id": team.id})
                is not None
            )
            if not already_exists:
                session.add(DBTeamSeason(season=season, team=team))

        session.flush()
        return season

    @classmethod
    def removeTeams(cls, session: Session, obj_id, team_ids):
        season = session.get(cls, obj_id)
        if not season:
            raise Exception(f"Season not found by id: {obj_id}")
        for team_id in team_ids:
            team = session.get(DBTeam, team_id)
            if not team:
                raise Exception(f"Team not found by id: {team_id}")
            team_season = session.get(
                DBTeamSeason, {"season_id": obj_id, "team_id": team_id}
            )
            if not team_season:
                raise Exception(
                    f"Team not part of the season, team id: {team_id}, season id {obj_id}"
                )
            session.delete(team_season)
        session.flush()
        return season

    @classmethod
    def addMaps(cls, session: Session, obj_id, map_ids):
        season = session.get(cls, obj_id)
        if not season:
            raise Exception(f"Season not found by id: {obj_id}")
        for map_id in map_ids:
            map = session.get(DBMap, map_id)
            if not map:
                raise Exception(f"Map not found by id: {map_id}")
            already_exists = (
                session.get(DBMapSeason, {"season_id": obj_id, "map_id": map.id})
                is not None
            )
            if not already_exists:
                session.add(DBMapSeason(season=season, map=map))

        session.flush()
        return season

    @classmethod
    def removeMaps(cls, session: Session, obj_id, map_ids):
        season = session.get(cls, obj_id)
        if not season:
            raise Exception(f"Season not found by id: {obj_id}")
        for map_id in map_ids:
            map = session.get(DBMap, map_id)
            if not map:
                raise Exception(f"Map not found by id: {map_id}")
            map_season = session.get(
                DBMapSeason, {"season_id": obj_id, "map_id": map.id}
            )
            if not map_season:
                raise Exception(
                    f"Map not part of the season, map id: {map_id}, season id {obj_id}"
                )
            session.delete(map_season)

        session.flush()
        return season

    @classmethod
    def addUserSignup(cls, session: Session, obj_id, user_ids):
        season = session.get(cls, obj_id)
        if not season:
            raise Exception(f"Season not found by id: {obj_id}")
        for user_id in user_ids:
            user = session.get(DBUser, user_id)
            if not user:
                raise Exception(f"User not found by id: {user_id}")
            already_exists = (
                session.get(
                    DBUserSeasonSignup, {"season_id": obj_id, "user_id": user.id}
                )
                is not None
            )
            if not already_exists:
                session.add(DBUserSeasonSignup(season=season, user=user))

        session.flush()
        return season

    @classmethod
    def removeUserSignup(cls, session: Session, obj_id, user_ids):
        season = session.get(cls, obj_id)
        if not season:
            raise Exception(f"Season not found by id: {obj_id}")
        for user_id in user_ids:
            user = session.get(DBUser, user_id)
            if not user:
                raise Exception(f"User not found by id: {user_id}")
            user_season = session.get(
                DBUserSeasonSignup, {"season_id": obj_id, "user_id": user.id}
            )
            if not user_season:
                raise Exception(
                    f"User not signed up for the season, user id: {user_id}, season id {obj_id}"
                )
            session.delete(user_season)

        session.flush()
        return season
