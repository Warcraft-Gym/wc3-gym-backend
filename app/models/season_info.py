"""What one team scored in one season.

The row is the team_season link table; this is the shape the API sends
for it, under the name seasons_info on a team.
"""

from sqlmodel import SQLModel

from app.models.season import SeasonPublic


class SeasonInfoBase(SQLModel):
    season_id: int | None = None
    final_score: int | None = None
    points_available: int | None = None
    points_against: int | None = None


class SeasonInfoUpdate(SeasonInfoBase):
    pass


class SeasonInfoPublic(SeasonInfoBase):
    season: SeasonPublic | None = None

    @classmethod
    def from_team_season(cls, season_info):
        if not season_info:
            return None

        return cls(
            season_id=season_info.season_id,
            final_score=season_info.final_score,
            points_available=season_info.points_available,
            points_against=season_info.points_against,
            season=SeasonPublic.from_season(season_info.season)
            if season_info.season
            else None,
        )

    def to_dict(self) -> dict:
        return self.model_dump(mode="json")
