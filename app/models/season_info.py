"""What one team scored in one season.

The row is the team_season link table; this is the shape the API sends
for it, under the name seasons_info on a team. app.services.derived fills
final_score, points_against and points_available from the series.
"""

from typing import TYPE_CHECKING, Any, Self

from sqlmodel import SQLModel

if TYPE_CHECKING:
    from app.models.team_season import DBTeamSeason


class SeasonInfoPublic(SQLModel):
    season_id: int | None = None
    final_score: int | None = None
    points_available: int | None = None
    points_against: int | None = None

    @classmethod
    def from_team_season(cls, season_info: "DBTeamSeason | None") -> Self | None:
        if not season_info:
            return None

        return cls(season_id=season_info.season_id)

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")
