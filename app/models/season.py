from datetime import date
from typing import TYPE_CHECKING, Annotated, Any, Self

from sqlalchemy.orm import Session
from sqlmodel import Field, Relationship, SQLModel

from app.models.base import DBModel
from app.models.map import MapPublic
from app.models.relationships import DBMapSeason, DBTeamSeason, DBUserSeasonSignup
from app.models.types import EmptyToNone, IsoDate, LenientDate, NumToStr

if TYPE_CHECKING:
    from app.models.relationships import DBUserTeamSeason


class SeasonBase(SQLModel):
    name: Annotated[str, NumToStr] = Field(max_length=50)
    number_weeks: int
    series_per_week: int
    pick_ban: Annotated[str | None, NumToStr] = Field(default=None, max_length=100)
    start_date: Annotated[date | None, LenientDate] = None
    end_date: Annotated[date | None, LenientDate] = None
    discordRole: Annotated[str | None, NumToStr] = Field(default=None, max_length=50)


class Season(SeasonBase, DBModel, table=True):
    __tablename__ = "seasons"

    id: int | None = Field(default=None, primary_key=True)
    user_teams: list["DBUserTeamSeason"] = Relationship(
        back_populates="season", sa_relationship_kwargs={"cascade": "all, delete"}
    )
    teams: list["DBTeamSeason"] = Relationship(
        back_populates="season", sa_relationship_kwargs={"cascade": "all, delete"}
    )
    maps: list["DBMapSeason"] = Relationship(
        back_populates="season", sa_relationship_kwargs={"cascade": "all, delete"}
    )
    signup_users: list["DBUserSeasonSignup"] = Relationship(
        back_populates="season", sa_relationship_kwargs={"cascade": "all, delete"}
    )

    @classmethod
    def addTeams(cls, session: Session, obj_id: int, team_ids: list[int]) -> Self:
        from app.models.team import Team

        season = session.get(cls, obj_id)
        if not season:
            raise Exception(f"Season not found by id: {obj_id}")
        for team_id in team_ids:
            team = session.get(Team, team_id)
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
    def removeTeams(cls, session: Session, obj_id: int, team_ids: list[int]) -> Self:
        from app.models.team import Team

        season = session.get(cls, obj_id)
        if not season:
            raise Exception(f"Season not found by id: {obj_id}")
        for team_id in team_ids:
            team = session.get(Team, team_id)
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
    def addMaps(cls, session: Session, obj_id: int, map_ids: list[int]) -> Self:
        from app.models.map import Map

        season = session.get(cls, obj_id)
        if not season:
            raise Exception(f"Season not found by id: {obj_id}")
        for map_id in map_ids:
            map = session.get(Map, map_id)
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
    def removeMaps(cls, session: Session, obj_id: int, map_ids: list[int]) -> Self:
        from app.models.map import Map

        season = session.get(cls, obj_id)
        if not season:
            raise Exception(f"Season not found by id: {obj_id}")
        for map_id in map_ids:
            map = session.get(Map, map_id)
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
    def addUserSignup(cls, session: Session, obj_id: int, user_ids: list[int]) -> Self:
        from app.models.user import User

        season = session.get(cls, obj_id)
        if not season:
            raise Exception(f"Season not found by id: {obj_id}")
        for user_id in user_ids:
            user = session.get(User, user_id)
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
    def removeUserSignup(
        cls, session: Session, obj_id: int, user_ids: list[int]
    ) -> Self:
        from app.models.user import User

        season = session.get(cls, obj_id)
        if not season:
            raise Exception(f"Season not found by id: {obj_id}")
        for user_id in user_ids:
            user = session.get(User, user_id)
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


class SeasonCreate(SeasonBase):
    pass


class SeasonUpdate(SQLModel):
    name: Annotated[str | None, NumToStr] = None
    number_weeks: int | None = None
    series_per_week: int | None = None
    pick_ban: Annotated[str | None, NumToStr] = None
    start_date: Annotated[date | None, LenientDate] = None
    end_date: Annotated[date | None, LenientDate] = None
    discordRole: Annotated[str | None, NumToStr] = None


class SeasonPublic(SeasonBase):
    id: int | None = None
    # The short form of a season carries the name and nothing else, so the
    # counts and the dates read null there.
    number_weeks: int | None = None
    series_per_week: int | None = None
    start_date: Annotated[IsoDate | None, LenientDate] = None
    end_date: Annotated[IsoDate | None, LenientDate] = None
    maps: Annotated[list[MapPublic] | None, EmptyToNone] = None
    # Nothing fills this. It is part of the response shape that the public
    # pages read, so the field stays and always reads null.
    user_signup: Annotated[list[Any] | None, EmptyToNone] = None

    @classmethod
    def from_season(cls, season: Season | None) -> Self | None:
        if not season:
            return None

        return cls(
            id=season.id,
            name=season.name,
            number_weeks=season.number_weeks,
            series_per_week=season.series_per_week,
            pick_ban=season.pick_ban,
            start_date=season.start_date,
            end_date=season.end_date,
            maps=[
                MapPublic.model_validate(map_season.map)
                for map_season in (season.maps or [])
                if map_season and map_season.map
            ],
            discordRole=season.discordRole,
        )

    @classmethod
    def from_season_reduced(cls, season: Season | None) -> Self | None:
        """The name and the id only. Used where a season is a label on
        another object rather than the subject of the response."""
        if not season:
            return None

        return cls(id=season.id, name=season.name)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")
