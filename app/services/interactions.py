"""The Discord interactions the adapter forwards.

The adapter (wc3-gym-discord-bot) checks Discord's signature, answers a
deferred private reply and forwards the payload as is. This module checks
the same signature again, so the route trusts Discord and nothing else, then
runs the command and replies through the interaction token: a private edit
of the deferred reply, or a public follow-up in the channel.
"""

import json
import os
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
from fastapi.responses import JSONResponse

from app.core.exceptions import ApiError
from app.core.query import QueryUtil
from app.models.series import SeriesPublic
from app.models.team import TeamReduced
from app.models.types import utcnow
from app.models.user import UserPublic
from app.services import discord, discord_roles, player_series
from app.services.series import SeriesService
from app.services.users import UserService

# Interaction types Discord sends
PING, COMMAND, AUTOCOMPLETE = 1, 2, 4
PONG, AUTOCOMPLETE_RESULT = 1, 8

# The guild's slash commands, as PUT to Discord by `just discord-commands`
COMMANDS: list[dict[str, Any]] = [
    {
        "name": "upcoming",
        "description": "The series scheduled in the next days",
        "options": [
            {
                "type": 4,
                "name": "days",
                "description": "How many days ahead, 7 unless given",
                "min_value": 1,
                "max_value": 60,
            },
            {"type": 5, "name": "fantasy", "description": "Only the fantasy matches"},
        ],
    },
    {
        "name": "schedule",
        "description": "Set the date and time of one of your series",
        "options": [
            {
                "type": 4,
                "name": "series",
                "description": "One of your series this season",
                "required": True,
                "autocomplete": True,
            },
            {
                "type": 3,
                "name": "when_utc",
                "description": "In UTC, as YYYY-MM-DD HH:MM",
                "required": True,
            },
        ],
    },
]
# A reply is public in the channel, or a private edit of the deferred "thinking" reply
PUBLIC, PRIVATE = True, False


def verified(headers: Mapping[str, str], body: bytes) -> bool:
    """True when the body carries Discord's signature over timestamp + body."""
    key = os.getenv("DISCORD_PUBLIC_KEY")
    if not key:
        raise ApiError(503, {"error": "DISCORD_PUBLIC_KEY is not set"})
    try:
        Ed25519PublicKey.from_public_bytes(bytes.fromhex(key)).verify(
            bytes.fromhex(headers.get("x-signature-ed25519", "")),
            headers.get("x-signature-timestamp", "").encode() + body,
        )
    except (InvalidSignature, ValueError):
        return False
    return True


def options_of(payload: dict[str, Any]) -> dict[str, Any]:
    return {
        option["name"]: option["value"]
        for option in payload.get("data", {}).get("options", [])
    }


def caller(payload: dict[str, Any]) -> tuple[str, str]:
    """The Discord id and display name of the member who sent the interaction."""
    user = payload.get("member", {}).get("user") or payload.get("user", {})
    return str(user.get("id")), user.get("global_name") or user.get("username") or "?"


def _series_line(series: SeriesPublic) -> str:
    def side(player: UserPublic | None, team: TeamReduced | None) -> str:
        name = (player.name if player else None) or "?"
        return f"{name} ({team.name})" if team else name

    match = series.match
    stamp = f"<t:{int(series.date_time.timestamp())}:f>" if series.date_time else "TBD"
    line = f"{stamp} · Wk {match.playday if match else '?'} · "
    line += side(series.player1, match.team1 if match else None)
    line += " vs " + side(series.player2, match.team2 if match else None)
    if series.caster:
        line += f" · twitch.tv/{series.caster}"
    return line + f" · #{series.id}"


def upcoming(
    payload: dict[str, Any], series_service: SeriesService, user_service: UserService
) -> tuple[dict[str, Any], bool]:
    """/upcoming days fantasy: the current season's series in the window, in order."""
    options = options_of(payload)
    days = int(options.get("days", 7))
    season_id = discord_roles.current_season()
    if season_id is None:
        return {"content": "No current season."}, PUBLIC
    start = utcnow()
    query = f"date_time >= {start.isoformat()} and date_time <= {(start + timedelta(days=days)).isoformat()}"
    if options.get("fantasy"):
        query += " and is_fantasy_match == True"
    rows = series_service.search_for_season(
        season_id, QueryUtil.parse_query(query), sort="date_time"
    )
    if not rows:
        return {"content": f"No series in the next {days} days."}, PUBLIC
    return {
        "embeds": [
            {
                "title": f"Series in the next {days} days",
                "description": "\n".join(_series_line(row) for row in rows),
                "color": 0x4A4DB8,
            }
        ]
    }, PUBLIC


def own_series(
    payload: dict[str, Any], series_service: SeriesService, user_service: UserService
) -> list[SeriesPublic]:
    """The caller's series of the current season, soonest first."""
    discord_id, _ = caller(payload)
    users = user_service.find_by_discord_id(discord_id)
    season_id = discord_roles.current_season()
    if not users or season_id is None:
        return []
    query = f"player1_id == {users[0].id} or player2_id == {users[0].id}"
    return series_service.search_for_season(
        season_id, QueryUtil.parse_query(query), sort="date_time"
    )


def schedule(
    payload: dict[str, Any], series_service: SeriesService, user_service: UserService
) -> tuple[dict[str, Any], bool]:
    """/schedule series when_utc: the same write as the dashboard, same rules."""
    options = options_of(payload)
    try:
        when = datetime.fromisoformat(str(options["when_utc"]).replace(" ", "T"))
    except (KeyError, ValueError):
        return {"content": "Give the time in UTC as YYYY-MM-DD HH:MM."}, PRIVATE
    if when.tzinfo is None:
        when = when.replace(tzinfo=UTC)
    discord_id, discord_tag = caller(payload)
    result = player_series.update_player_series(
        int(options["series"]),
        {"date_time": when.isoformat()},
        discord_id=discord_id,
        discord_tag=discord_tag,
        user_service=user_service,
        series_service=series_service,
    )
    if isinstance(result, JSONResponse):
        return {"content": json.loads(bytes(result.body))["error"]}, PRIVATE
    line = _series_line(series_service.get(int(options["series"])))
    return {"content": f"Scheduled by <@{discord_id}>: {line}"}, PUBLIC


def choices(
    payload: dict[str, Any], series_service: SeriesService, user_service: UserService
) -> list[dict[str, Any]]:
    """The autocomplete choices for a `series` option: the caller's own series."""
    typed = next(
        (
            str(option.get("value", "")).lower()
            for option in payload.get("data", {}).get("options", [])
            if option.get("focused")
        ),
        "",
    )
    names = (
        (_series_line(row).split(" · ", 1)[1][:100], row.id)
        for row in own_series(payload, series_service, user_service)
    )
    return [
        {"name": name, "value": series_id}
        for name, series_id in names
        if typed in name.lower()
    ][:25]


HANDLERS = {"upcoming": upcoming, "schedule": schedule}


def handle(
    payload: dict[str, Any], series_service: SeriesService, user_service: UserService
) -> dict[str, Any]:
    """Run one interaction and answer what the adapter relays to Discord.

    A command's answer goes to Discord through the interaction token here, so
    the route's own answer only says it was handled.
    """
    kind = payload.get("type")
    if kind == PING:
        return {"type": PONG}
    if kind == AUTOCOMPLETE:
        found = (
            choices(payload, series_service, user_service)
            if payload["data"]["name"] in HANDLERS
            else []
        )
        return {"type": AUTOCOMPLETE_RESULT, "data": {"choices": found}}
    application_id, token = payload["application_id"], payload["token"]
    handler = HANDLERS.get(payload["data"]["name"]) if kind == COMMAND else None
    if handler is None:
        discord.edit_reply(application_id, token, {"content": "Unknown command."})
        return {"ok": True}
    message, public = handler(payload, series_service, user_service)
    if public:
        discord.post_reply(application_id, token, message)
    else:
        discord.edit_reply(application_id, token, message)
    return {"ok": True}


def register_commands() -> list[str]:
    return discord.register_guild_commands(COMMANDS)
