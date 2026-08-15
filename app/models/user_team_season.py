"""One player's season on one team: the user_team_season table.

The row links a user, a team and a season and carries the per-season
record. UserTeamSeasonStatsPublic is the shape the API sends for it,
under the name gnl_stats on a user.
"""

from typing import TYPE_CHECKING, Annotated, Any, Self

from sqlalchemy import JSON, Column
from sqlmodel import Field, Relationship, SQLModel

from app.models.base import DBModel
from app.models.season import SeasonPublic
from app.models.team_reduced import TeamReduced
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
    games: int | None = None
    wins: int | None = None
    losses: int | None = None
    # Array of opponent races: ['HU', 'OC', 'UD', etc.]
    matchup_history: list[Any] | None = Field(
        default=None, sa_column=Column("matchup_history", JSON)
    )
    # Additional columns can be added here if needed
    user: "User" = Relationship(back_populates="team_seasons")
    team: "Team" = Relationship(back_populates="user_seasons")
    season: "Season" = Relationship(back_populates="user_teams")


class UserTeamSeasonStatsPublic(SQLModel):
    user_id: int | None = None
    team_id: int | None = None
    games: int | None = None
    team: TeamReduced | None = None
    wins: int | None = None
    losses: int | None = None
    season_id: int | None = None
    season: SeasonPublic | None = None
    matchup_history: Annotated[list[Any], NoneToList] = []

    @classmethod
    def from_user_team_season(cls, uts: DBUserTeamSeason | None) -> Self | None:
        if not uts:
            return None

        return cls(
            user_id=uts.user_id,
            team_id=uts.team_id,
            games=uts.games,
            team=TeamReduced.from_team(uts.team) if uts.team else None,
            wins=uts.wins,
            losses=uts.losses,
            season_id=uts.season_id,
            season=SeasonPublic.from_season_reduced(uts.season) if uts.season else None,
            matchup_history=uts.matchup_history if uts.matchup_history else [],
        )

    def to_dict(self) -> dict[str, Any]:
        return self.model_dump(mode="json")
