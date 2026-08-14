from typing import Annotated

from app.schemas.base import APISchema, NumToStr
from app.schemas.map import Map
from app.schemas.season import Season
from app.schemas.team import TeamReduced

DB_FIELDS = {
    "team1_id",
    "team2_id",
    "season_id",
    "playday",
    "date_frame",
    "fixed_map_id",
    "team1_score",
    "team2_score",
}


class Match(APISchema):
    id: int | None = None
    team1_id: int | None = None
    team1: TeamReduced | None = None
    team2_id: int | None = None
    team2: TeamReduced | None = None
    season_id: int | None = None
    season: Season | None = None
    playday: int | None = None
    # date_frame receives numeric cells from the xlsx import.
    date_frame: Annotated[str | None, NumToStr] = None
    fixed_map_id: int | None = None
    fixed_map: Map | None = None
    team1_score: int | None = None
    team2_score: int | None = None

    def to_db_dict(self):
        return self.model_dump(include=DB_FIELDS)

    @classmethod
    def from_dbmatch(cls, match):
        return cls(
            id=match.id,
            team1_id=match.team1_id,
            team1=TeamReduced.from_dbteam(match.team1) if match.team1 else None,
            team2_id=match.team2_id,
            team2=TeamReduced.from_dbteam(match.team2) if match.team2 else None,
            season_id=match.season_id,
            season=Season.from_dbseason_reduced(match.season) if match.season else None,
            playday=match.playday,
            date_frame=match.date_frame,
            fixed_map_id=match.fixed_map_id,
            fixed_map=Map.from_dbmap(match.fixed_map) if match.fixed_map else None,
            team1_score=match.team1_score,
            team2_score=match.team2_score,
        )
