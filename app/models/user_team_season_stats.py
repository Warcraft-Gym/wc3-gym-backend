"""The per-season record of one player in one team.

The row is the user_team_season link table; this is the shape the API
sends for it, under the name gnl_stats on a user.
"""

from typing import Annotated, Any

from sqlmodel import SQLModel

from app.models.season import SeasonPublic
from app.models.team_reduced import TeamReduced
from app.models.types import NoneToList


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
    def from_user_team_season(cls, uts):
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

    def to_dict(self) -> dict:
        return self.model_dump(mode="json")
