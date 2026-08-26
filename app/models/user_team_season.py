"""One player's season on one team: the user_team_season table.

The row links a user, a team and a season. UserTeamSeasonStatsPublic is the
shape the API sends for it, under the name gnl_stats on a user, and
app.services.derived counts its record from the series the player stood in.
"""

from typing import TYPE_CHECKING, Annotated, Any, Self

from sqlmodel import Field, Relationship, SQLModel

from app.models.base import DBModel
from app.models.types import NoneToList

if TYPE_CHECKING:
    from app.models.season import Season
    from app.models.team import Team
    from app.models.user import User


class DBUserTeamSeason(DBModel, table=True):
    __tablename__ = "user_team_season"
    user_id: int = Field(foreign_key="users.id", primary_key=True)
    team_id: int = Field(foreign_key="teams.id", primary_key=True)
    season_id: int = Field(foreign_key="seasons.id", primary_key=True)
    user: "User" = Relationship(back_populates="team_seasons")
    team: "Team" = Relationship(back_populates="user_seasons")
    season: "Season" = Relationship(back_populates="user_teams")


class UserTeamSeasonStatsPublic(SQLModel):
    """The record itself. The team and the season are ids here, and
    app.services.derived fills the four counted fields."""

    user_id: int | None = None
    team_id: int | None = None
    games: int | None = None
    wins: int | None = None
    losses: int | None = None
    season_id: int | None = None
    matchup_history: Annotated[list[Any], NoneToList] = []

    @classmethod
    def from_user_team_season(cls, uts: DBUserTeamSeason | None) -> Self | None:
        if not uts:
            return None

        return cls(
            user_id=uts.user_id,
            team_id=uts.team_id,
            season_id=uts.season_id,
        )
