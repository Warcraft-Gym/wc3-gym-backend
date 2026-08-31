"""FastAPI dependencies: the admin guard and the service graph.

The services are stateless besides their references to each other, so one
instance of each serves the process. Constructing them touches no
database; the engine work happens in create_app.
"""

import logging
import os
from functools import cache
from typing import Annotated, Any

import jwt
from clerk_backend_api import AuthenticateRequestOptions, Clerk
from clerk_backend_api.models import OAuthAccessToken
from fastapi import Depends, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from app.core.db import Session
from app.core.exceptions import ApiError
from app.core.security import decode_token
from app.models.clerk_account import ClerkAccount
from app.services import admins, discord
from app.services.availability import AvailabilityService
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
from app.services.series_veto import SeriesVetoService
from app.services.settings import SettingsService
from app.services.teams import TeamService
from app.services.users import UserService

_bearer = HTTPBearer(auto_error=False)

Credentials = Annotated[HTTPAuthorizationCredentials | None, Depends(_bearer)]

logger = logging.getLogger(__name__)


@cache
def _clerk() -> Clerk:
    return Clerk(bearer_auth=os.getenv("CLERK_SECRET_KEY"))


def clerk_claims(request: Request) -> dict[str, Any]:
    """The Discord identity and the role behind the request's Clerk session.

    Clerk verifies the session token locally (its JWKS is cached). The Discord
    account behind the Clerk user is read from clerk_account, filled on the
    first request. An admin is one the database or ADMIN_DISCORD_IDS names, so
    it needs no guild read; everyone else is a member of the guild or a guest.
    A captain is one the database names on a current-season team, never a
    Discord role. Every check is live, so a kick, grant or seat change shows
    on the next request.
    """
    # production lists its exact origins; Vercel previews set it empty because their origin changes per branch
    parties = os.getenv("CLERK_AUTHORIZED_PARTIES", "http://localhost:5173")
    state = _clerk().authenticate_request(
        request,
        AuthenticateRequestOptions(
            authorized_parties=parties.replace(" ", "").split(",") if parties else None
        ),
    )
    if not state.is_signed_in or state.payload is None:
        logger.warning(
            "Clerk refused the session: %s (bearer %s)",
            state.message,
            "present" if request.headers.get("authorization") else "missing",
        )
        raise ApiError(401, {"error": state.message or "Not signed in"})

    clerk_user_id = str(state.payload["sub"])
    discord_id = _discord_id(clerk_user_id)
    claims: dict[str, Any] = {"sub": discord_id, "clerk_user_id": clerk_user_id}
    if admins.is_admin(discord_id):
        return _view_as(request, claims | {"role": "admin"})
    claims["role"] = discord.role_for(discord_id)
    if claims["role"] == "member":
        settings = settings_service.get_settings_dict()
        seat = team_service.captain_seat(discord_id, settings.get("current_gnl_season"))
        if seat:
            claims |= {"role": "captain", "team_id": seat[0], "season_id": seat[1]}
    return claims


def _view_as(request: Request, claims: dict[str, Any]) -> dict[str, Any]:
    """The role an admin's X-View-As header asks to be seen as, for debugging.

    The rewrite happens where every guard reads the role, so an admin viewing
    as a member meets the same 403s a member would. The real role stays in
    actual_role, which /me answers so the switch stays visible. A viewed
    captain names its team with X-View-Team; the season is the
    current_gnl_season setting, as captain_seat reads it.
    """
    role = request.headers.get("x-view-as")
    if role not in ("captain", "member", "guest"):
        return claims
    claims |= {"role": role, "actual_role": "admin"}
    team = request.headers.get("x-view-team", "")
    if role == "captain" and team.isdigit():
        season = settings_service.get_settings_dict().get("current_gnl_season")
        claims["team_id"] = int(team)
        if season and season.isdigit():
            claims["season_id"] = int(season)
    return claims


def _discord_id(clerk_user_id: str) -> str:
    """The Discord id behind a Clerk user: one row, written by its first request."""
    with Session.begin() as session:
        account = session.get(ClerkAccount, clerk_user_id)
        if account:
            return account.discord_id
    return discord_token(clerk_user_id).provider_user_id


def discord_token(clerk_user_id: str) -> OAuthAccessToken:
    """The Discord OAuth token Clerk holds for that user, for reads as the account.

    Every answer rewrites the clerk_account row, so a Discord account relinked
    in Clerk is picked up by the next login (/me reads the token every time).
    """
    tokens = _clerk().users.get_o_auth_access_token(
        user_id=clerk_user_id, provider="oauth_discord"
    )
    if not tokens:
        raise ApiError(401, {"error": "No Discord account on this login"})
    with Session.begin() as session:
        session.merge(
            ClerkAccount(
                clerk_user_id=clerk_user_id, discord_id=tokens[0].provider_user_id
            )
        )
    return tokens[0]


def require_login(request: Request, credentials: Credentials) -> dict[str, Any]:
    """Admit the admin token or a Clerk session, and answer the claims.

    A guest is admitted too: it logs in and reads the public pages.
    """
    if credentials is None:
        raise ApiError(401, {"error": "Missing Authorization Header"})
    try:
        claims = decode_token(credentials.credentials)
    except jwt.InvalidTokenError:
        return clerk_claims(request)
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


def require_captain(request: Request, credentials: Credentials) -> dict[str, Any]:
    """Admit a captain of the current season, or an admin."""
    claims = require_login(request, credentials)
    if claims.get("role") not in ("captain", "admin") and claims["sub"] != "admin":
        raise ApiError(403, {"error": "Captains only"})
    return claims


RequireAdmin = Annotated[str, Depends(require_admin)]
RequireLogin = Annotated[dict[str, Any], Depends(require_login)]
RequireCaptain = Annotated[dict[str, Any], Depends(require_captain)]


settings_service = SettingsService()
user_service = UserService(settings_app_service=settings_service)
team_service = TeamService(user_app_service=user_service)
match_service = MatchService()
season_service = SeasonService(user_app_service=user_service)
series_service = SeriesService()
series_veto_service = SeriesVetoService()
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
availability_service = AvailabilityService()


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


def get_series_veto_service() -> SeriesVetoService:
    return series_veto_service


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


def get_availability_service() -> AvailabilityService:
    return availability_service


SettingsServiceDep = Annotated[SettingsService, Depends(get_settings_service)]
UserServiceDep = Annotated[UserService, Depends(get_user_service)]
TeamServiceDep = Annotated[TeamService, Depends(get_team_service)]
MatchServiceDep = Annotated[MatchService, Depends(get_match_service)]
SeasonServiceDep = Annotated[SeasonService, Depends(get_season_service)]
SeriesServiceDep = Annotated[SeriesService, Depends(get_series_service)]
SeriesVetoServiceDep = Annotated[SeriesVetoService, Depends(get_series_veto_service)]
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
AvailabilityServiceDep = Annotated[
    AvailabilityService, Depends(get_availability_service)
]
