"""The Discord calls and the role a logged-in account gets.

The account's Discord token comes from Clerk, so the Clerk Discord
connection must request the `identify guilds guilds.members.read` scopes.
"""

import os
from typing import Any

import requests

from app.core.exceptions import ApiError

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
