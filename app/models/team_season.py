"""One team's run through one season: the team_season table.

The row links a team and a season and carries the coaches.
season_info.py holds the shape the API sends for it.
"""

from typing import TYPE_CHECKING

from sqlmodel import Field, Relationship

from app.models.base import DBModel
from app.models.user import User

if TYPE_CHECKING:
    from app.models.season import Season
    from app.models.team import Team


class DBTeamSeason(DBModel, table=True):
    __tablename__ = "team_season"
    team_id: int = Field(foreign_key="teams.id", primary_key=True)
    season_id: int = Field(foreign_key="seasons.id", primary_key=True)
    # Team coaches (up to 3)
    coach_1_id: int | None = Field(default=None, foreign_key="users.id")
    coach_2_id: int | None = Field(default=None, foreign_key="users.id")
    coach_3_id: int | None = Field(default=None, foreign_key="users.id")
    # Relationships
    team: "Team" = Relationship(back_populates="season_info")
    season: "Season" = Relationship(back_populates="teams")
    coach_1: User | None = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[DBTeamSeason.coach_1_id]"}
    )
    coach_2: User | None = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[DBTeamSeason.coach_2_id]"}
    )
    coach_3: User | None = Relationship(
        sa_relationship_kwargs={"foreign_keys": "[DBTeamSeason.coach_3_id]"}
    )
