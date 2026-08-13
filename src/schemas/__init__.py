"""Pydantic API schemas (formerly the hand-written DTOs in src/dtos).

Import order matters only for readability; the model_rebuild() loop at the
bottom resolves the cross-module forward references (season <-> user and
user_team_season_stats -> team).
"""

from src.schemas import season as _season_module
from src.schemas import user_team_season_stats as _uts_module
from src.schemas.base import APISchema
from src.schemas.draft_series import DraftSeries
from src.schemas.fantasy_bet import FantasyBet
from src.schemas.fantasy_team import FantasyTeam
from src.schemas.koth_event import KothEvent
from src.schemas.koth_match import KothMatch
from src.schemas.koth_match_participant import KothMatchParticipant
from src.schemas.koth_signup import KothSignup
from src.schemas.map import Map
from src.schemas.match import Match
from src.schemas.player_career_stats import PlayerCareerStats
from src.schemas.season import Season
from src.schemas.season_info import SeasonInfo
from src.schemas.series import Series
from src.schemas.settings import Settings
from src.schemas.team import Team, TeamReduced
from src.schemas.user import User
from src.schemas.user_team_season_stats import UserTeamSeasonStats
from src.schemas.w3c_stats import W3CStats

# Make the forward-referenced classes visible in the modules that declared
# them as strings, then rebuild every model so all references resolve.
_season_module.User = User
_uts_module.TeamReduced = TeamReduced

_ALL_MODELS = [
    Map,
    W3CStats,
    Settings,
    KothSignup,
    KothMatchParticipant,
    KothMatch,
    KothEvent,
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
    "KothEvent",
    "KothMatch",
    "KothMatchParticipant",
    "KothSignup",
    "Map",
    "Match",
    "PlayerCareerStats",
    "Season",
    "SeasonInfo",
    "Series",
    "Settings",
    "Team",
    "TeamReduced",
    "User",
    "UserTeamSeasonStats",
    "W3CStats",
]
