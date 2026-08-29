"""The Discord calls and the role a logged-in account gets.

The account's Discord token comes from Clerk, so the Clerk Discord
connection must request the `identify guilds guilds.members.read` scopes.
"""

import logging
import os
from collections.abc import Iterable
from typing import Any

import requests

from app.core.exceptions import ApiError

logger = logging.getLogger(__name__)

API_URL = "https://discord.com/api/v10"

# Seconds a Discord call can hold the thread before it fails.
REQUEST_TIMEOUT = 10

# The Discord permission bit that makes a role a guild administrator.
ADMINISTRATOR = 0x8


def _user_get(access_token: str, path: str) -> requests.Response:
    return requests.get(
        f"{API_URL}{path}",
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=REQUEST_TIMEOUT,
    )


def identify(access_token: str) -> dict[str, Any]:
    """The Discord account behind that access token."""
    response = _user_get(access_token, "/users/@me")
    if not response.ok:
        raise ApiError(502, {"error": "Discord refused the login"})
    return dict(response.json())


def avatar_url(account: dict[str, Any]) -> str | None:
    """The account's avatar image, or None when it has the default one."""
    avatar = account.get("avatar")
    if not avatar:
        return None
    return f"https://cdn.discordapp.com/avatars/{account['id']}/{avatar}.png"


def role_for(access_token: str, discord_id: str, admin_role: str | None = None) -> str:
    """The account's role: "admin", "member", or "guest" outside the guild.

    Everything is read with the account's own token, so the app needs no bot
    in the guild.
    """
    guild_id = os.getenv("DISCORD_GUILD_ID", "")
    guilds = _user_get(access_token, "/users/@me/guilds")
    if not guilds.ok:
        raise ApiError(502, {"error": "Discord refused the membership check"})
    guild = next((row for row in guilds.json() if str(row.get("id")) == guild_id), None)
    if guild is None:
        # A guest logs in and sees the public pages; the routes of a player refuse it.
        return "guest"

    allowlist = os.getenv("ADMIN_DISCORD_IDS", "").replace(" ", "").split(",")
    if discord_id in allowlist:
        return "admin"
    if guild.get("owner") or int(guild.get("permissions", 0)) & ADMINISTRATOR:
        return "admin"
    if not admin_role:
        return "member"

    member = _user_get(access_token, f"/users/@me/guilds/{guild_id}/member")
    roles = set(member.json().get("roles", [])) if member.ok else set()
    return "admin" if admin_role in roles else "member"


def _bot_headers() -> dict[str, str] | None:
    """The bot's authorization, or None when no bot token is configured."""
    token = os.getenv("DISCORD_BOT_TOKEN")
    return {"Authorization": f"Bot {token}"} if token else None


def set_role(discord_ids: Iterable[str], role_id: str, grant: bool) -> None:
    """Grant or revoke a guild role. Discord refusing it is a warning, not a failure."""
    headers = _bot_headers()
    if not headers or not role_id:
        return
    guild_id = os.getenv("DISCORD_GUILD_ID", "")
    method = "PUT" if grant else "DELETE"
    for discord_id in discord_ids:
        url = f"{API_URL}/guilds/{guild_id}/members/{discord_id}/roles/{role_id}"
        try:
            response = requests.request(
                method, url, headers=headers, timeout=REQUEST_TIMEOUT
            )
        except requests.RequestException as error:
            logger.warning("Discord role write failed for %s: %s", discord_id, error)
            continue
        if not response.ok:
            logger.warning(
                "Discord refused the role write for %s: %s",
                discord_id,
                response.status_code,
            )


def without_role(discord_ids: Iterable[str], role_id: str) -> list[str]:
    """Which of those accounts the guild does not show the role on.

    Empty when no bot token is configured, so the page shows no chip.
    """
    headers = _bot_headers()
    if not headers or not role_id:
        return []
    guild_id = os.getenv("DISCORD_GUILD_ID", "")
    missing = []
    for discord_id in discord_ids:
        url = f"{API_URL}/guilds/{guild_id}/members/{discord_id}"
        try:
            response = requests.request(
                "GET", url, headers=headers, timeout=REQUEST_TIMEOUT
            )
        except requests.RequestException as error:
            logger.warning("Discord member read failed for %s: %s", discord_id, error)
            continue
        if not response.ok or role_id not in response.json().get("roles", []):
            missing.append(discord_id)
    return missing
