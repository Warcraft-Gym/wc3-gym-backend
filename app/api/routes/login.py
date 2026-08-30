import os
from typing import Any

from fastapi import APIRouter
from fastapi.responses import RedirectResponse

from app.api.deps import RequireLogin, TeamServiceDep, UserServiceDep
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
    if data.token != os.getenv("ADMIN_TOKEN"):
        raise ApiError(401, {"error": "Bad admin token"})
    return {
        "access_token": create_access_token("admin", int(os.getenv("TOKEN_TIME", "60")))
    }


@router.get("/me")
def me(
    claims: RequireLogin, user_service: UserServiceDep, team_service: TeamServiceDep
) -> dict[str, Any]:
    """The logged-in account, the users row linked to its Discord id, and the season."""
    # The admin token carries no Discord account, so it reads no name.
    superadmin = "token" not in claims
    account = {} if superadmin else discord.identify(claims["token"])
    users = user_service.find_by_discord_id(claims["sub"])
    user = users[0] if users else None
    season_id = discord_roles.current_season()
    # A captain's claims name the team it captains this season.
    team_id = claims.get("team_id")
    team = team_service.get(team_id) if team_id else None
    return {
        "discord_id": claims["sub"],
        "name": "Super Admin"
        if superadmin
        else account.get("global_name") or account.get("username"),
        "avatar": discord.avatar_url(account),
        "role": claims.get("role", "admin"),
        "user": user,
        "superadmin": superadmin,
        "signed_up": bool(
            user and any(season.id == season_id for season in user.signup_seasons)
        ),
        "season_id": season_id,
        "team": {"id": team.id, "name": team.name} if team else None,
    }
