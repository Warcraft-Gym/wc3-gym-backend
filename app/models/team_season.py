"""One team's run through one season: the team_season table.

The row links a team and a season. The captains of that season are the
team_season_captain rows. season_info.py holds the shape the API sends for it.
"""

from typing import TYPE_CHECKING

from sqlmodel import Field, Relationship

from app.models.base import DBModel

if TYPE_CHECKING:
    from app.models.season import Season
    from app.models.team import Team


class DBTeamSeason(DBModel, table=True):
    __tablename__ = "team_season"
    team_id: int = Field(foreign_key="teams.id", primary_key=True)
    season_id: int = Field(index=True, foreign_key="seasons.id", primary_key=True)
    # Relationships
    team: "Team" = Relationship(back_populates="season_info")
    season: "Season" = Relationship(back_populates="teams")
