from datetime import date
from typing import TYPE_CHECKING, Annotated, Any, Self

from sqlmodel import Field, Relationship, SQLModel

from app.models.base import DBModel
from app.models.map import MapPublic
from app.models.types import IsoDate, LenientDate, NoneToList, NumToStr

if TYPE_CHECKING:
    from app.models.relationships import DBMapSeason, DBUserSeasonSignup
    from app.models.team_season import DBTeamSeason
    from app.models.user_team_season import DBUserTeamSeason


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
    # The short form of a season carries only the name, so these read null
    number_weeks: int | None = None
    series_per_week: int | None = None
    start_date: Annotated[IsoDate | None, LenientDate] = None
    end_date: Annotated[IsoDate | None, LenientDate] = None
    maps: Annotated[list[MapPublic], NoneToList] = []
    # Always empty; the public pages read this field
    user_signup: Annotated[list[Any], NoneToList] = []

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

    @classmethod
    def from_season_without_maps(cls, season: Season | None) -> Self | None:
        """Every scalar field of the season, without the map pool."""
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
            discordRole=season.discordRole,
        )

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")
