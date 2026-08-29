from typing import TYPE_CHECKING, Annotated, Self

from sqlalchemy import Index
from sqlmodel import Field, Relationship, SQLModel

from app.models.base import DBModel
from app.models.map import Map, MapPublic
from app.models.season import SeasonPublic
from app.models.team_reduced import TeamReduced
from app.models.types import NumToStr

if TYPE_CHECKING:
    from app.models.season import Season
    from app.models.team import Team


class MatchBase(SQLModel):
    team1_id: int = Field(index=True, foreign_key="teams.id", ondelete="CASCADE")
    team2_id: int = Field(index=True, foreign_key="teams.id", ondelete="CASCADE")
    season_id: int = Field(index=True, foreign_key="seasons.id", ondelete="CASCADE")
    playday: int
    fixed_map_id: int | None = Field(index=True, default=None, foreign_key="maps.id")
    # date_frame receives numeric cells from the xlsx import.
    date_frame: Annotated[str | None, NumToStr] = Field(default=None, max_length=50)


class Match(MatchBase, DBModel, table=True):
    __tablename__ = "matches"
    # Two teams meet once on a playday. A-vs-B and B-vs-A are different rows.
    __table_args__ = (
        Index(
            "uq_matches_season_id_team1_id_team2_id_playday",
            "season_id",
            "team1_id",
            "team2_id",
            "playday",
            unique=True,
        ),
    )

    id: int | None = Field(default=None, primary_key=True)
    team1: "Team" = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[Match.team1_id]"}
    )
    team2: "Team" = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[Match.team2_id]"}
    )
    season: "Season" = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[Match.season_id]"}
    )
    fixed_map: Map | None = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[Match.fixed_map_id]"}
    )


class MatchCreate(MatchBase):
    pass


class MatchUpdate(SQLModel):
    team1_id: int | None = None
    team2_id: int | None = None
    season_id: int | None = None
    playday: int | None = None
    fixed_map_id: int | None = None
    date_frame: Annotated[str | None, NumToStr] = None


class MatchPublic(MatchBase):
    id: int
    team1_id: int | None = None
    team2_id: int | None = None
    season_id: int | None = None
    playday: int | None = None
    team1: TeamReduced | None = None
    team2: TeamReduced | None = None
    season: SeasonPublic | None = None
    fixed_map: MapPublic | None = None
    # app.services.derived sums the two team scores from the series
    team1_score: int | None = None
    team2_score: int | None = None

    @classmethod
    def from_match(cls, match: Match) -> Self:
        return cls(
            id=match.id,
            team1_id=match.team1_id,
            team1=TeamReduced.from_team(match.team1) if match.team1 else None,
            team2_id=match.team2_id,
            team2=TeamReduced.from_team(match.team2) if match.team2 else None,
            season_id=match.season_id,
            season=SeasonPublic.from_season_reduced(match.season)
            if match.season
            else None,
            playday=match.playday,
            date_frame=match.date_frame,
            fixed_map_id=match.fixed_map_id,
            fixed_map=MapPublic.model_validate(match.fixed_map)
            if match.fixed_map
            else None,
        )

    @classmethod
    def from_match_with_season(cls, match: Match) -> Self:
        """The match with every scalar of its season, without the map pool."""
        public = cls.from_match(match)
        if match.season:
            public.season = SeasonPublic.from_season_without_maps(match.season)
        return public
