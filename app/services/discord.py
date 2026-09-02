"""The Discord calls and the guild membership behind a login.

The account's Discord token comes from Clerk and only identifies the
account (`identify` scope); the bot reads the guild. Membership is all the
guild decides: app.services.admins says who administers the site.
"""

import logging
import os
from collections import Counter
from typing import Any

import requests

from app.core.exceptions import ApiError
from app.models.discord_role_binding import GuildRole

logger = logging.getLogger(__name__)

API_URL = "https://discord.com/api/v10"

# Seconds a Discord call can hold the thread before it fails.
REQUEST_TIMEOUT = 10


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


def role_for(discord_id: str) -> str:
    """The account's role as the bot sees it: "member", or "guest" outside the guild."""
    guild_id = os.getenv("DISCORD_GUILD_ID", "")
    member = _bot_get(f"/guilds/{guild_id}/members/{discord_id}")
    if member is not None and member.status_code == 404:
        # A guest logs in and sees the public pages; the routes of a player refuse it.
        return "guest"
    if member is None or not member.ok:
        raise ApiError(502, {"error": "Discord refused the membership check"})
    return "member"


def _bot_headers() -> dict[str, str] | None:
    """The bot's authorization, or None when no bot token is configured."""
    token = os.getenv("DISCORD_BOT_TOKEN")
    return {"Authorization": f"Bot {token}"} if token else None


def set_role(discord_id: str, role_id: str, grant: bool) -> None:
    """Grant or revoke a guild role. Discord refusing it is a warning, not a failure."""
    headers = _bot_headers()
    if not headers or not role_id:
        return
    guild_id = os.getenv("DISCORD_GUILD_ID", "")
    method = "PUT" if grant else "DELETE"
    url = f"{API_URL}/guilds/{guild_id}/members/{discord_id}/roles/{role_id}"
    try:
        response = requests.request(
            method, url, headers=headers, timeout=REQUEST_TIMEOUT
        )
    except requests.RequestException as error:
        logger.warning("Discord role write failed for %s: %s", discord_id, error)
        return
    if not response.ok:
        logger.warning(
            "Discord refused the role write for %s: %s",
            discord_id,
            response.status_code,
        )


def guild_members() -> dict[str, set[str]] | None:
    """The roles every guild member holds, by account id; None when the guild has no answer.

    One paged listing instead of one read per account. Needs the Server
    Members intent on the bot; a refusal answers None and the caller falls
    back to member reads.
    """
    guild_id = os.getenv("DISCORD_GUILD_ID", "")
    members: dict[str, set[str]] = {}
    after = "0"
    while True:
        response = _bot_get(f"/guilds/{guild_id}/members?limit=1000&after={after}")
        if response is None or not response.ok:
            if response is not None:
                logger.warning(
                    "Discord refused the member list: %s", response.status_code
                )
            return None
        page = response.json()
        for member in page:
            members[member["user"]["id"]] = set(member.get("roles", []))
        if len(page) < 1000:
            return members
        after = page[-1]["user"]["id"]


def guild_roles() -> list[GuildRole]:
    """Every guild role but @everyone, highest first; empty when the guild has no answer.

    A role is manageable when it sits below the bot's own highest role and
    Discord does not manage it itself, which is exactly what the bot can grant.
    """
    guild_id = os.getenv("DISCORD_GUILD_ID", "")
    response = _bot_get(f"/guilds/{guild_id}/roles")
    if response is None or not response.ok:
        return []
    roles = [role for role in response.json() if role["id"] != guild_id]
    positions = {role["id"]: role["position"] for role in roles}
    bot = _bot_get(f"/guilds/{guild_id}/members/@me")
    held = bot.json().get("roles", []) if bot is not None and bot.ok else []
    top = max((positions.get(role_id, 0) for role_id in held), default=0)
    counts = Counter(
        role_id for member in (guild_members() or {}).values() for role_id in member
    )
    return sorted(
        (
            GuildRole(
                id=role["id"],
                name=role["name"],
                color=f"#{role['color']:06x}" if role.get("color") else None,
                position=role["position"],
                members=counts[role["id"]],
                manageable=role["position"] < top and not role.get("managed", False),
            )
            for role in roles
        ),
        key=lambda role: role.position,
        reverse=True,
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
