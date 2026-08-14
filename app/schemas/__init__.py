"""Pydantic API schemas.

Import order matters only for readability; the model_rebuild() loop at the
bottom resolves the cross-module forward references (season <-> user and
user_team_season_stats -> team).
"""

from app.schemas import season as _season_module
from app.schemas import user_team_season_stats as _uts_module
from app.schemas.base import APISchema
from app.schemas.draft_series import DraftSeries
from app.schemas.fantasy_bet import FantasyBet
from app.schemas.fantasy_team import FantasyTeam
from app.schemas.match import Match
from app.schemas.player_career_stats import PlayerCareerStats
from app.schemas.season import Season
from app.schemas.season_info import SeasonInfo
from app.schemas.series import Series
from app.schemas.team import Team, TeamReduced
from app.schemas.user import User
from app.schemas.user_team_season_stats import UserTeamSeasonStats

# Make the forward-referenced classes visible in the modules that declared
# them as strings, then rebuild every model so all references resolve.
_season_module.User = User
_uts_module.TeamReduced = TeamReduced

_ALL_MODELS = [
    Season,
    UserTeamSeasonStats,
    User,
    SeasonInfo,
    TeamReduced,
    Team,
    Match,
    Series,
    DraftSeries,
    FantasyTeam,
    FantasyBet,
    PlayerCareerStats,
]
for _model in _ALL_MODELS:
    _model.model_rebuild(force=True)

__all__ = [
    "APISchema",
    "DraftSeries",
    "FantasyBet",
    "FantasyTeam",
    "Match",
    "PlayerCareerStats",
    "Season",
    "SeasonInfo",
    "Series",
    "Team",
    "TeamReduced",
    "User",
    "UserTeamSeasonStats",
]
