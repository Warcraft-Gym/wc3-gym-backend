import os
import secrets
from typing import Any
from urllib.parse import urlencode

import jwt
import requests
from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse

from app.api.deps import (
    RequireLogin,
    SeasonServiceDep,
    TeamServiceDep,
    UserServiceDep,
)
from app.core.config import frontend_url
from app.core.exceptions import ApiError
from app.core.security import (
    SESSION_KIND,
    SESSION_MINUTES,
    create_access_token,
    decode_token,
)
from app.models.login import LoginRequest
from app.services import discord, discord_roles, organizers

router = APIRouter(tags=["Authentication"])

AUTHORIZE_URL = "https://discord.com/oauth2/authorize"
STATE_KIND = "discord_state"


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


def _discord_callback_url(request: Request) -> str:
    """This backend's callback; Vercel names the public scheme in x-forwarded-proto."""
    url = request.url_for("discord_callback")
    return str(url.replace(scheme=request.headers.get("x-forwarded-proto", url.scheme)))


def _to_frontend(path: str) -> RedirectResponse:
    return RedirectResponse(
        f"{frontend_url()}{path}", headers={"Cache-Control": "no-store"}
    )


@router.get("/auth/discord/start")
def start_discord_login(request: Request) -> RedirectResponse:
    """Send the browser to Discord's consent page; its state is a signed token that names no one."""
    client_id = os.getenv("DISCORD_APPLICATION_ID")
    if not client_id or not os.getenv("DISCORD_CLIENT_SECRET"):
        raise ApiError(503, {"error": "Discord login is not configured"})
    query = urlencode(
        {
            "response_type": "code",
            "scope": "identify",
            "client_id": client_id,
            "redirect_uri": _discord_callback_url(request),
            "state": create_access_token("start", 10, STATE_KIND),
            "prompt": "none",
        }
    )
    return RedirectResponse(f"{AUTHORIZE_URL}?{query}", status_code=302)


@router.get("/auth/discord/callback", name="discord_callback")
def discord_callback(
    request: Request, code: str = "", state: str = "", error: str = ""
) -> RedirectResponse:
    """Send the browser to the frontend with a session token for the Discord account.

    The token rides in the URL fragment, which the browser never sends to a
    server or in a Referer. The role is not in it: every request reads it live.
    """
    if error or not code:
        return _to_frontend("/login?login=error&reason=denied")
    try:
        valid_state = decode_token(state).get("type") == STATE_KIND
    except jwt.InvalidTokenError:
        valid_state = False
    if not valid_state:
        return _to_frontend("/login?login=error&reason=state")
    try:
        account = discord.identify(
            discord.exchange_code(code, _discord_callback_url(request))
        )
        discord_id = str(account["id"])
    except (requests.RequestException, ApiError, KeyError, ValueError):
        return _to_frontend("/login?login=error&reason=token")
    session = create_access_token(
        discord_id,
        SESSION_MINUTES,
        SESSION_KIND,
        {
            "name": account.get("global_name") or account.get("username"),
            "avatar": account.get("avatar"),
        },
    )
    return _to_frontend(f"/sso-callback#{urlencode({'token': session})}")


@router.get("/me")
def me(
    request: Request,
    claims: RequireLogin,
    user_service: UserServiceDep,
    team_service: TeamServiceDep,
    season_service: SeasonServiceDep,
) -> dict[str, Any]:
    """The logged-in account, the users row linked to its Discord id, and every
    season that is still running, with this account's place in each."""
    # The admin token carries no Discord account, so it reads no name. A local
    # dev login names a player but carries no avatar, so it rewrites none.
    superadmin = claims.get("sub") == "admin"
    account: dict[str, Any] = (
        {"id": claims["sub"], "avatar": claims["avatar"]} if "avatar" in claims else {}
    )
    users = user_service.find_by_discord_id(claims["sub"])
    user = users[0] if users else None
    avatar = discord.avatar_url(account)
    # the profile keeps the picture Discord shows now, so pages read it without a login
    if account and user and user.avatar_url != avatar:
        user_service.set_avatar(user.id, avatar)
        user.avatar_url = avatar
    season_id = discord_roles.current_season()
    seats = claims.get("seats", [])
    captained = {seat["season_id"] for seat in seats}
    # Every season the account can still act in, newest first; a complete one is done
    seasons = season_service.open_seasons()
    signed_up = {season.id for season in (user.signup_seasons if user else [])}
    rosters = team_service.player_teams(user.id) if user else {}
    # The nav links one team: the seat this account captains in the season this
    # answer names, else the roster row of that season.
    seat_team = next(
        (seat["team_id"] for seat in seats if seat["season_id"] == season_id), None
    )
    captained_team = (seat_team, team_service.name(seat_team)) if seat_team else None
    roster = rosters.get(season_id) if season_id else None
    organizer, requested = organizers.standing(claims)
    return {
        "discord_id": claims["sub"],
        "name": "Super Admin"
        if superadmin
        else claims.get("name") or (user.name if user else None),
        "avatar": avatar,
        "role": claims.get("role", "admin"),
        # the role behind an X-View-As switch, so the frontend keeps the switch visible
        "actual_role": claims.get("actual_role", claims.get("role", "admin")),
        "user": user,
        "superadmin": superadmin,
        # A member with an organizer grant creates events; an admin always may
        "organizer": organizer,
        # A request for the grant waits for an admin's answer
        "organizer_request": "pending" if requested and not organizer else None,
        "signed_up": season_id in signed_up,
        "season_id": season_id,
        "team": {"id": captained_team[0], "name": captained_team[1]}
        if captained_team
        else {"id": roster[0], "name": roster[1]}
        if roster
        else None,
        # The (team, season) pairs this account captains, one per running season
        "seats": seats,
        "seasons": [
            {
                "id": season.id,
                "name": season.name,
                "league_short_name": season.league_short_name,
                "phase": season.phase,
                "signups_open": season.signups_open,
                "scheduling_enabled": season.scheduling_enabled,
                "checkin_days": season.checkin_days,
                "start_date": season.start_date,
                "end_date": season.end_date,
                "signed_up": season.id in signed_up,
                "team": {"id": season_team[0], "name": season_team[1]}
                if (season_team := rosters.get(season.id))
                else None,
                "captain": season.id in captained,
            }
            for season in seasons
        ],
    }
