import os
from typing import Any

from fastapi import APIRouter
from fastapi.responses import RedirectResponse

from app.api.deps import RequireLogin, UserServiceDep
from app.core.exceptions import ApiError
from app.core.security import create_access_token
from app.models.login import LoginRequest
from app.services import discord

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
def me(claims: RequireLogin, user_service: UserServiceDep) -> dict[str, Any]:
    """The logged-in account and the users row linked to its Discord id."""
    # The admin token carries no Discord account, so it reads no name.
    account = discord.identify(claims["token"]) if "token" in claims else {}
    users = user_service.find_by_discord_id(claims["sub"])
    return {
        "discord_id": claims["sub"],
        "name": account.get("global_name") or account.get("username"),
        "avatar": discord.avatar_url(account),
        "role": claims.get("role", "admin"),
        "user": users[0] if users else None,
    }
