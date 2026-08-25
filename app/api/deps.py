"""FastAPI dependencies: the admin guard and the service graph.

The services are stateless besides their references to each other, so one
instance of each serves the process. Constructing them touches no
database; the engine work happens in create_app.
"""

from typing import Annotated, Any

import jwt
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.security import decode_token
from app.services.draft_series import DraftSeriesService
from app.services.fantasy_bets import FantasyBetService
from app.services.fantasy_scores import FantasyScoreService
from app.services.fantasy_teams import FantasyTeamService
from app.services.koth import KothService
from app.services.maps import MapService
from app.services.matches import MatchService
from app.services.player_career_stats import PlayerCareerStatsService
from app.services.seasons import SeasonService
from app.services.series import SeriesService
from app.services.settings import SettingsService
from app.services.teams import TeamService
from app.services.users import UserService


class AuthError(Exception):
    """A request without a valid token.

    Clients read the status and the {"error": ...} body: 401 for a missing header or an
    expired token, 422 for a malformed token or the wrong token type."""

    def __init__(self, message: str, status_code: int = 401) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code


_bearer = HTTPBearer(auto_error=False)

_Credentials = Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)]


def _decode(credentials: _Credentials) -> dict[str, Any]:
    if credentials is None:
        raise AuthError("Missing Authorization Header")
    try:
        return decode_token(credentials.credentials)
    except jwt.ExpiredSignatureError as e:
        raise AuthError("Token has expired") from e
    except jwt.InvalidTokenError as e:
        raise AuthError(str(e), status_code=422) from e


def require_admin(credentials: _Credentials) -> str:
    """Admit a valid access token and answer its subject."""
    claims = _decode(credentials)
    if claims.get("type") != "access":
        raise AuthError("Only non-refresh tokens are allowed", status_code=422)
    return claims["sub"]


def require_refresh(credentials: _Credentials) -> str:
    """Admit a valid refresh token and answer its subject."""
    claims = _decode(credentials)
    if claims.get("type") != "refresh":
        raise AuthError("Only refresh tokens are allowed", status_code=422)
    return claims["sub"]


RequireAdmin = Annotated[str, Depends(require_admin)]
RequireRefresh = Annotated[str, Depends(require_refresh)]


settings_service = SettingsService()
user_service = UserService(settings_app_service=settings_service)
team_service = TeamService(user_app_service=user_service)
match_service = MatchService()
season_service = SeasonService()
series_service = SeriesService(user_app_service=user_service)
draft_series_service = DraftSeriesService()
map_service = MapService()
fantasy_bet_service = FantasyBetService(settings_app_service=settings_service)
fantasy_team_service = FantasyTeamService()
fantasy_score_service = FantasyScoreService(
    fantasy_team_service=fantasy_team_service,
    fantasy_bet_service=fantasy_bet_service,
    series_app_service=series_service,
    team_app_service=team_service,
)
koth_service = KothService(settings_app_service=settings_service)
stats_service = PlayerCareerStatsService()


def get_settings_service() -> SettingsService:
    return settings_service


def get_user_service() -> UserService:
    return user_service


def get_team_service() -> TeamService:
    return team_service


def get_match_service() -> MatchService:
    return match_service


def get_season_service() -> SeasonService:
    return season_service


def get_series_service() -> SeriesService:
    return series_service


def get_draft_series_service() -> DraftSeriesService:
    return draft_series_service


def get_map_service() -> MapService:
    return map_service


def get_fantasy_bet_service() -> FantasyBetService:
    return fantasy_bet_service


def get_fantasy_team_service() -> FantasyTeamService:
    return fantasy_team_service


def get_fantasy_score_service() -> FantasyScoreService:
    return fantasy_score_service


def get_koth_service() -> KothService:
    return koth_service


def get_stats_service() -> PlayerCareerStatsService:
    return stats_service


SettingsServiceDep = Annotated[SettingsService, Depends(get_settings_service)]
UserServiceDep = Annotated[UserService, Depends(get_user_service)]
TeamServiceDep = Annotated[TeamService, Depends(get_team_service)]
MatchServiceDep = Annotated[MatchService, Depends(get_match_service)]
SeasonServiceDep = Annotated[SeasonService, Depends(get_season_service)]
SeriesServiceDep = Annotated[SeriesService, Depends(get_series_service)]
DraftSeriesServiceDep = Annotated[DraftSeriesService, Depends(get_draft_series_service)]
MapServiceDep = Annotated[MapService, Depends(get_map_service)]
FantasyBetServiceDep = Annotated[FantasyBetService, Depends(get_fantasy_bet_service)]
FantasyTeamServiceDep = Annotated[FantasyTeamService, Depends(get_fantasy_team_service)]
FantasyScoreServiceDep = Annotated[
    FantasyScoreService, Depends(get_fantasy_score_service)
]
KothServiceDep = Annotated[KothService, Depends(get_koth_service)]
StatsServiceDep = Annotated[PlayerCareerStatsService, Depends(get_stats_service)]
