"""The Discord calls and the guild membership behind a login.

The account's Discord token comes from Clerk and only identifies the
account (`identify` scope); the bot reads the guild. Membership is all the
guild decides: app.services.admins says who administers the site.
"""

import base64
import logging
import os
from collections import Counter
from functools import cache
from pathlib import Path
from time import sleep
from typing import Any

import requests

from app.core.exceptions import ApiError
from app.models.discord_role_binding import GuildRole

logger = logging.getLogger(__name__)

API_URL = "https://discord.com/api/v10"

# Seconds a Discord call can hold the thread before it fails.
REQUEST_TIMEOUT = 10
# The longest a channel call waits out a rate limit before it gives up.
RETRY_WAIT_LIMIT = 5.0


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


def guild_member_list() -> list[dict[str, Any]] | None:
    """Every guild member, paged; None when the guild has no answer.

    One paged listing instead of one read per account. Needs the Server
    Members intent on the bot; a refusal answers None and the caller falls
    back to member reads.
    """
    guild_id = os.getenv("DISCORD_GUILD_ID", "")
    members: list[dict[str, Any]] = []
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
        members += page
        if len(page) < 1000:
            return members
        after = page[-1]["user"]["id"]


def guild_members() -> dict[str, set[str]] | None:
    """The roles every guild member holds, by account id; None when the guild has no answer."""
    members = guild_member_list()
    if members is None:
        return None
    return {member["user"]["id"]: set(member.get("roles", [])) for member in members}


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
    members = guild_members() or {}
    # The bot is a member like any other; its own id comes from /users/@me
    me = _bot_get("/users/@me")
    bot_id = me.json().get("id", "") if me is not None and me.ok else ""
    held = members.get(bot_id)
    if held is None:
        bot = _bot_get(f"/guilds/{guild_id}/members/{bot_id}") if bot_id else None
        held = set(bot.json().get("roles", [])) if bot is not None and bot.ok else set()
    top = max((positions.get(role_id, 0) for role_id in held), default=0)
    counts = Counter(
        role_id for roles_held in members.values() for role_id in roles_held
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


# Interaction replies. The interaction token is the authorization; no bot token is needed.
def _interaction_call(
    method: str,
    application_id: str,
    token: str,
    path: str,
    message: dict[str, Any] | None,
) -> None:
    url = f"{API_URL}/webhooks/{application_id}/{token}{path}"
    try:
        response = requests.request(method, url, json=message, timeout=REQUEST_TIMEOUT)
    except requests.RequestException as error:
        logger.warning("Discord interaction call failed for %s: %s", path, error)
        return
    if not response.ok:
        logger.warning(
            "Discord refused the interaction call %s: %s", path, response.status_code
        )


def edit_reply(application_id: str, token: str, message: dict[str, Any]) -> None:
    """Replace the deferred reply the adapter sent, private as it was."""
    _interaction_call("PATCH", application_id, token, "/messages/@original", message)


def _channel_call(
    method: str, path: str, message: dict[str, Any]
) -> requests.Response | None:
    """A call on a channel as the bot. None with no bot token, or when Discord
    is unreachable or refuses it."""
    headers = _bot_headers()
    if not headers:
        return None
    try:
        response = requests.request(
            method,
            f"{API_URL}/channels/{path}",
            headers=headers,
            json=message,
            timeout=REQUEST_TIMEOUT,
        )
        # A rate limit names its wait; one wait is enough for the pace discord_posts keeps
        if response.status_code == 429:
            wait = float(response.json().get("retry_after", RETRY_WAIT_LIMIT))
            sleep(min(wait, RETRY_WAIT_LIMIT))
            response = requests.request(
                method,
                f"{API_URL}/channels/{path}",
                headers=headers,
                json=message,
                timeout=REQUEST_TIMEOUT,
            )
    except requests.RequestException as error:
        logger.warning("Discord channel call failed for %s: %s", path, error)
        return None
    if not response.ok:
        logger.warning(
            "Discord refused the channel call %s: %s", path, response.status_code
        )
        return None
    return response


def post_to_channel(channel_id: str, message: dict[str, Any]) -> str | None:
    """Post a message in a channel as the bot. The id of the message, or None
    when it did not go out."""
    response = _channel_call("POST", f"{channel_id}/messages", message)
    return str(response.json()["id"]) if response else None


def edit_channel_message(
    channel_id: str, message_id: str, message: dict[str, Any]
) -> None:
    """Replace a message the bot posted in a channel."""
    _channel_call("PATCH", f"{channel_id}/messages/{message_id}", message)


def post_reply(
    application_id: str, token: str, channel_id: str, message: dict[str, Any]
) -> str | None:
    """Post the answer in the channel as the bot, and drop the private "thinking" reply.

    A follow-up through the interaction token cannot leave the deferred reply's
    private state (the first one edits it), so the public post uses the bot
    token. Without a bot token, or when Discord refuses the post, the answer
    stays in the private reply instead of going nowhere. The id of the channel
    post, or None when the answer stayed private.
    """
    message_id = post_to_channel(channel_id, message)
    if message_id:
        _interaction_call("DELETE", application_id, token, "/messages/@original", None)
        return message_id
    edit_reply(application_id, token, message)
    return None


@cache
def app_emojis(application_id: str) -> dict[str, str]:
    """The application's emojis by name, read once per process; empty until
    `just discord-emojis` uploads them, without an application id, or when
    Discord cannot be reached."""
    if not application_id:
        return {}
    response = _bot_get(f"/applications/{application_id}/emojis")
    if response is None or not response.ok:
        return {}
    return {item["name"]: item["id"] for item in response.json()["items"]}


def emoji_url(emoji_id: str) -> str:
    """Where Discord serves an emoji as an image."""
    return f"https://cdn.discordapp.com/emojis/{emoji_id}.png"


def upload_app_emoji(name: str, image: bytes, mime: str = "image/png") -> bool:
    """Upload one image as an application emoji under the name. An emoji that
    exists already is left as it is, and False says so: Discord cannot swap an
    emoji's image, so a new picture needs the old emoji deleted first."""
    headers = _bot_headers()
    application_id = os.getenv("DISCORD_APPLICATION_ID", "")
    if not headers or not application_id:
        raise ApiError(
            503, {"error": "DISCORD_BOT_TOKEN and DISCORD_APPLICATION_ID are needed"}
        )
    if name in app_emojis(application_id):
        return False
    encoded = base64.b64encode(image).decode()
    response = requests.request(
        "POST",
        f"{API_URL}/applications/{application_id}/emojis",
        headers=headers,
        json={"name": name, "image": f"data:{mime};base64,{encoded}"},
        timeout=REQUEST_TIMEOUT,
    )
    if not response.ok:
        raise ApiError(response.status_code, {"error": response.text})
    return True


def upload_app_emojis(folder: Path) -> list[str]:
    """Upload every PNG in the folder as an application emoji named by its
    file stem; an emoji that exists already is left as it is."""
    return [
        png.stem
        for png in sorted(folder.glob("*.png"))
        if upload_app_emoji(png.stem, png.read_bytes())
    ]


def register_guild_commands(commands: list[dict[str, Any]]) -> list[str]:
    """Replace the guild's slash commands with these; guild commands update at once."""
    headers = _bot_headers()
    application_id = os.getenv("DISCORD_APPLICATION_ID", "")
    guild_id = os.getenv("DISCORD_GUILD_ID", "")
    if not headers or not application_id or not guild_id:
        raise ApiError(
            503,
            {
                "error": "DISCORD_BOT_TOKEN, DISCORD_APPLICATION_ID and DISCORD_GUILD_ID are needed"
            },
        )
    response = requests.request(
        "PUT",
        f"{API_URL}/applications/{application_id}/guilds/{guild_id}/commands",
        headers=headers,
        json=commands,
        timeout=REQUEST_TIMEOUT,
    )
    if not response.ok:
        raise ApiError(
            502,
            {
                "error": f"Discord refused the commands: {response.status_code} {response.text}"
            },
        )
    return [command["name"] for command in response.json()]
