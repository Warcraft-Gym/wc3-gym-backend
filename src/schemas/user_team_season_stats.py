from typing import TYPE_CHECKING, Annotated, Any

from src.schemas.base import APISchema, NoneToList
from src.schemas.season import Season

if TYPE_CHECKING:
    from src.schemas.team import TeamReduced


class UserTeamSeasonStats(APISchema):
    user_id: int | None = None
    team_id: int | None = None
    games: int | None = None
    team: 'TeamReduced | None' = None
    wins: int | None = None
    losses: int | None = None
    season_id: int | None = None
    season: Season | None = None
    matchup_history: Annotated[list[Any], NoneToList] = []

    @classmethod
    def from_db_user_team_season(cls, uts):
        if not uts:
            return None

        from src.schemas.team import TeamReduced

        return cls(
            user_id=uts.user_id,
            team_id=uts.team_id,
            games=uts.games,
            team=TeamReduced.from_dbteam(uts.team) if uts.team else None,
            wins=uts.wins,
            losses=uts.losses,
            season_id=uts.season_id,
            season=Season.from_dbseason_reduced(uts.season) if uts.season else None,
            matchup_history=uts.matchup_history if uts.matchup_history else [],
        )

    @staticmethod
    def schema():
        from src.schemas.season import Season
        from src.schemas.team import Team
        return {
            'type': 'object',
            'properties': {
                'user_id': {'type': 'integer'},
                'team_id': {'type': 'integer'},
                'team': {'type': Team},
                'games': {'type': 'integer'},
                'wins': {'type': 'integer'},
                'losses': {'type': 'integer'},
                'season_id': {'type': 'integer'},
                'season': {'type': Season},
            }
        }
