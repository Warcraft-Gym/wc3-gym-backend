"""The Discord calls and the role a logged-in account gets.

The account's Discord token comes from Clerk and only identifies the
account (`identify` scope); the bot reads the guild.
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


def _bot_get(path: str) -> requests.Response | None:
    """A guild read as the bot; None with no bot token or when Discord is unreachable."""
    headers = _bot_headers()
    if not headers:
        return None
    try:
        return requests.request(
            "GET", f"{API_URL}{path}", headers=headers, timeout=REQUEST_TIMEOUT
        )
    except requests.RequestException as error:
        logger.warning("Discord read failed for %s: %s", path, error)
        return None


def role_for(discord_id: str, admin_role: str | None = None) -> str:
    """The account's role as the bot sees it: "admin", "member", or "guest" outside the guild."""
    guild_id = os.getenv("DISCORD_GUILD_ID", "")
    member = _bot_get(f"/guilds/{guild_id}/members/{discord_id}")
    if member is not None and member.status_code == 404:
        # A guest logs in and sees the public pages; the routes of a player refuse it.
        return "guest"
    if member is None or not member.ok:
        raise ApiError(502, {"error": "Discord refused the membership check"})
    roles = set(member.json().get("roles", []))

    allowlist = os.getenv("ADMIN_DISCORD_IDS", "").replace(" ", "").split(",")
    if discord_id in allowlist or (admin_role and admin_role in roles):
        return "admin"
    guild = _bot_get(f"/guilds/{guild_id}")
    if guild is None or not guild.ok:
        return "member"
    data = guild.json()
    if str(data.get("owner_id")) == discord_id:
        return "admin"
    admin_roles = {
        row["id"]
        for row in data.get("roles", [])
        if int(row.get("permissions", 0)) & ADMINISTRATOR
    }
    return "admin" if roles & admin_roles else "member"


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


def member_roles(discord_id: str) -> set[str] | None:
    """The guild roles that account holds, or None when the guild has no answer.

    None is the answer with no bot token, for an account outside the guild,
    and for a refused read: the caller leaves that account alone.
    """
    guild_id = os.getenv("DISCORD_GUILD_ID", "")
    response = _bot_get(f"/guilds/{guild_id}/members/{discord_id}")
    if response is None or response.status_code == 404:
        return None
    if not response.ok:
        logger.warning(
            "Discord refused the member read for %s: %s",
            discord_id,
            response.status_code,
        )
        return None
    return set(response.json().get("roles", []))
