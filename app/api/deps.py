"""FastAPI dependencies: the admin guard and the service graph.

The services are stateless besides their references to each other, so one
instance of each serves the process. Constructing them touches no
database; the engine work happens in create_app.
"""

import os
from functools import cache
from typing import Annotated, Any

import jwt
from clerk_backend_api import AuthenticateRequestOptions, Clerk
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.exceptions import ApiError
from app.core.security import decode_token
from app.services import discord
from app.services.draft_series import DraftSeriesService
from app.services.fantasy_bets import FantasyBetService
from app.services.fantasy_scores import FantasyScoreService
from app.services.fantasy_teams import FantasyTeamService
from app.services.koth import KothService
from app.services.ladder import LadderService
from app.services.maps import MapService
from app.services.matches import MatchService
from app.services.player_career_stats import PlayerCareerStatsService
from app.services.seasons import SeasonService
from app.services.series import SeriesService
from app.services.settings import SettingsService
from app.services.teams import TeamService
from app.services.users import UserService

_bearer = HTTPBearer(auto_error=False)

Credentials = Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)]


@cache
def _clerk() -> Clerk:
    return Clerk(bearer_auth=os.getenv("CLERK_SECRET_KEY"))


def _clerk_claims(request: Request) -> dict[str, Any]:
    """The Discord identity and guild role behind the request's Clerk session.

    Clerk verifies the session token and holds the account's Discord token;
    the guild and its roles are read with that token, as before.
    """
    # ponytail: one Clerk call and up to two Discord calls per request; cache
    # them on the Clerk session id if the latency shows.
    parties = os.getenv("CLERK_AUTHORIZED_PARTIES", "http://localhost:5173")
    state = _clerk().authenticate_request(
        request,
        AuthenticateRequestOptions(
            authorized_parties=parties.replace(" ", "").split(",")
        ),
    )
    if not state.is_signed_in or state.payload is None:
        raise ApiError(401, {"error": state.message or "Not signed in"})

    tokens = _clerk().users.get_o_auth_access_token(
        user_id=str(state.payload["sub"]), provider="oauth_discord"
    )
    if not tokens:
        raise ApiError(401, {"error": "No Discord account on this login"})

    discord_id = tokens[0].provider_user_id
    admin_role = settings_service.get_settings_dict().get("admin_role")
    return {
        "sub": discord_id,
        "role": discord.role_for(tokens[0].token, discord_id, admin_role),
        "token": tokens[0].token,
    }


def require_login(request: Request, credentials: Credentials) -> dict[str, Any]:
    """Admit the admin token or a Clerk session, and answer the claims.

    A guest is admitted too: it logs in and reads the public pages.
    """
    if credentials is None:
        raise ApiError(401, {"error": "Missing Authorization Header"})
    try:
        claims = decode_token(credentials.credentials)
    except jwt.InvalidTokenError:
        return _clerk_claims(request)
    if claims.get("type") != "access":
        raise ApiError(422, {"error": "Only access tokens are allowed"})
    return claims


def require_member(request: Request, credentials: Credentials) -> dict[str, Any]:
    """Admit an account that is in the guild; a guest reads nothing of its own."""
    claims = require_login(request, credentials)
    if claims.get("role") == "guest":
        raise ApiError(
            403, {"error": "No valid WC3 Gym server membership found for user"}
        )
    return claims


def require_admin(request: Request, credentials: Credentials) -> str:
    """Admit an admin access token and answer its subject."""
    claims = require_login(request, credentials)
    if claims.get("role") != "admin" and claims["sub"] != "admin":
        raise ApiError(403, {"error": "Admins only"})
    return claims["sub"]


RequireLogin = Annotated[dict[str, Any], Depends(require_login)]
RequireMember = Annotated[dict[str, Any], Depends(require_member)]


settings_service = SettingsService()
user_service = UserService(settings_app_service=settings_service)
team_service = TeamService(user_app_service=user_service)
match_service = MatchService()
season_service = SeasonService(user_app_service=user_service)
series_service = SeriesService()
draft_series_service = DraftSeriesService()
map_service = MapService()
fantasy_bet_service = FantasyBetService(settings_app_service=settings_service)
fantasy_team_service = FantasyTeamService()
fantasy_score_service = FantasyScoreService(
    fantasy_team_service=fantasy_team_service,
    fantasy_bet_service=fantasy_bet_service,
    series_app_service=series_service,
)
koth_service = KothService(settings_app_service=settings_service)
ladder_service = LadderService(settings_app_service=settings_service)
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


def get_ladder_service() -> LadderService:
    return ladder_service


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
LadderServiceDep = Annotated[LadderService, Depends(get_ladder_service)]
StatsServiceDep = Annotated[PlayerCareerStatsService, Depends(get_stats_service)]
