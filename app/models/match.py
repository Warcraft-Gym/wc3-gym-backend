from typing import TYPE_CHECKING, Annotated, Optional

from sqlmodel import Field, Relationship, SQLModel

from app.models.base import DBModel
from app.models.map import MapPublic
from app.models.season import SeasonPublic
from app.models.team_reduced import TeamReduced
from app.models.types import NumToStr

if TYPE_CHECKING:
    from app.models.map import Map
    from app.models.season import Season
    from app.models.team import Team


class MatchBase(SQLModel):
    team1_id: int = Field(foreign_key="teams.id", ondelete="CASCADE")
    team2_id: int = Field(foreign_key="teams.id", ondelete="CASCADE")
    season_id: int = Field(foreign_key="seasons.id", ondelete="CASCADE")
    playday: int
    team1_score: int | None = None
    team2_score: int | None = None
    fixed_map_id: int | None = Field(default=None, foreign_key="maps.id")
    # date_frame receives numeric cells from the xlsx import.
    date_frame: Annotated[str | None, NumToStr] = Field(default=None, max_length=50)


class Match(MatchBase, DBModel, table=True):
    __tablename__ = "matches"

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
    fixed_map: Optional["Map"] = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[Match.fixed_map_id]"}
    )


class MatchCreate(MatchBase):
    pass


class MatchUpdate(SQLModel):
    team1_id: int | None = None
    team2_id: int | None = None
    season_id: int | None = None
    playday: int | None = None
    team1_score: int | None = None
    team2_score: int | None = None
    fixed_map_id: int | None = None
    date_frame: Annotated[str | None, NumToStr] = None


class MatchPublic(MatchBase):
    id: int | None = None
    team1_id: int | None = None
    team2_id: int | None = None
    season_id: int | None = None
    playday: int | None = None
    team1: TeamReduced | None = None
    team2: TeamReduced | None = None
    season: SeasonPublic | None = None
    fixed_map: MapPublic | None = None

    @classmethod
    def from_match(cls, match):
        if not match:
            return None

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
            team1_score=match.team1_score,
            team2_score=match.team2_score,
        )

    def to_dict(self) -> dict:
        return self.model_dump(mode="json")
