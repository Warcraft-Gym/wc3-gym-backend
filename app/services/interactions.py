"""The Discord interactions the adapter forwards.

The adapter (wc3-gym-discord-bot) checks Discord's signature, answers a
deferred private reply and forwards the payload as is. This module checks
the same signature again, so the route trusts Discord and nothing else, then
runs the command and replies through the interaction token: a private edit
of the deferred reply, or a public follow-up in the channel.
"""

import os
from collections.abc import Mapping
from datetime import timedelta
from typing import Any

from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey

from app.core.exceptions import ApiError
from app.core.query import QueryUtil
from app.models.series import SeriesPublic
from app.models.team import TeamReduced
from app.models.types import utcnow
from app.models.user import UserPublic
from app.services import discord, discord_roles
from app.services.series import SeriesService

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
]


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


def upcoming(payload: dict[str, Any], series_service: SeriesService) -> dict[str, Any]:
    """/upcoming days fantasy: the current season's series in the window, in order."""
    options = options_of(payload)
    days = int(options.get("days", 7))
    season_id = discord_roles.current_season()
    if season_id is None:
        return {"content": "No current season."}
    start = utcnow()
    query = f"date_time >= {start.isoformat()} and date_time <= {(start + timedelta(days=days)).isoformat()}"
    if options.get("fantasy"):
        query += " and is_fantasy_match == True"
    rows = series_service.search_for_season(
        season_id, QueryUtil.parse_query(query), sort="date_time"
    )
    if not rows:
        return {"content": f"No series in the next {days} days."}
    return {
        "embeds": [
            {
                "title": f"Series in the next {days} days",
                "description": "\n".join(_series_line(row) for row in rows),
                "color": 0x4A4DB8,
            }
        ]
    }


def handle(payload: dict[str, Any], series_service: SeriesService) -> dict[str, Any]:
    """Run one interaction and answer what the adapter relays to Discord.

    A command's answer goes to Discord through the interaction token here, so
    the route's own answer only says it was handled.
    """
    kind = payload.get("type")
    if kind == PING:
        return {"type": PONG}
    if kind == AUTOCOMPLETE:
        return {"type": AUTOCOMPLETE_RESULT, "data": {"choices": []}}
    application_id, token = payload["application_id"], payload["token"]
    if kind == COMMAND and payload["data"]["name"] == "upcoming":
        discord.post_reply(application_id, token, upcoming(payload, series_service))
    else:
        discord.edit_reply(application_id, token, {"content": "Unknown command."})
    return {"ok": True}


def register_commands() -> list[str]:
    return discord.register_guild_commands(COMMANDS)
