import os
import secrets
from typing import Any

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from app.api.deps import (
    RequireLogin,
    TeamServiceDep,
    UserServiceDep,
    discord_token,
    refresh_claims,
)
from app.core.exceptions import ApiError
from app.core.security import create_access_token
from app.models.login import LoginRequest
from app.services import discord, discord_roles

router = APIRouter(tags=["Authentication"])


@router.get("/")
def index() -> RedirectResponse:
    """Send the browser to the API documentation."""
    return RedirectResponse("/docs", status_code=302)


@router.post("/login")
def login(data: LoginRequest) -> dict[str, str]:
    """Exchange the admin token for an access token."""
    expected = os.getenv("ADMIN_TOKEN")
    if not expected:
        raise ApiError(503, {"error": "ADMIN_TOKEN is not set"})
    if not secrets.compare_digest(data.token.encode(), expected.encode()):
        raise ApiError(401, {"error": "Bad admin token"})
    return {
        "access_token": create_access_token("admin", int(os.getenv("TOKEN_TIME", "60")))
    }


@router.get("/me")
def me(
    request: Request,
    claims: RequireLogin,
    user_service: UserServiceDep,
    team_service: TeamServiceDep,
) -> dict[str, Any]:
    """The logged-in account, the users row linked to its Discord id, and the season."""
    # The admin token carries no Discord account, so it reads no name.
    superadmin = "clerk_user_id" not in claims
    account: dict[str, Any] = {}
    if not superadmin:
        token = discord_token(claims["clerk_user_id"])
        if token.provider_user_id != claims["sub"]:
            # the frontend keeps this answer all session, so a Discord account
            # relinked in Clerk must show now, not one request later
            claims = refresh_claims(request)
        account = discord.identify(token.token)
    users = user_service.find_by_discord_id(claims["sub"])
    user = users[0] if users else None
    avatar = discord.avatar_url(account)
    # the profile keeps the picture Discord shows now, so pages read it without a login
    if account and user and user.avatar_url != avatar:
        user_service.set_avatar(user.id, avatar)
        user.avatar_url = avatar
    season_id = discord_roles.current_season()
    # A captain's claims name the team it captains this season. Any other member
    # is named by the roster row of that season, so the nav can link his team.
    team_id = claims.get("team_id")
    if not team_id and user and season_id:
        team_id = team_service.player_team(user.id, season_id)
    team = team_service.get(team_id) if team_id else None
    return {
        "discord_id": claims["sub"],
        "name": "Super Admin"
        if superadmin
        else account.get("global_name") or account.get("username"),
        "avatar": avatar,
        "role": claims.get("role", "admin"),
        # the role behind an X-View-As switch, so the frontend keeps the switch visible
        "actual_role": claims.get("actual_role", claims.get("role", "admin")),
        "user": user,
        "superadmin": superadmin,
        "signed_up": bool(
            user and any(season.id == season_id for season in user.signup_seasons)
        ),
        "season_id": season_id,
        "team": {"id": team.id, "name": team.name} if team else None,
    }
