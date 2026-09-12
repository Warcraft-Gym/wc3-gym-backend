"""/score: report a result from Discord, with one replay per game played.

The attachments Discord holds are moved into the bucket through the same presigned
links the browser uses, then the result goes through the write the dashboard uses,
so the veto rule and the best-of rule are the same in both places.
"""

import json
import os
from typing import Any

import requests
from fastapi.responses import JSONResponse

from app.core.exceptions import BadRequestError
from app.models.user import UserPublic
from app.services import discord, player_series, replays
from app.services.commands.base import (
    PRIVATE,
    PUBLIC,
    Services,
    caller,
    options_of,
    own_series,
)
from app.services.replays import MAX_BYTES

# What Discord accepts as an attachment option
ATTACHMENT = 11

COMMAND: dict[str, Any] = {
    "name": "score",
    "description": "Report the result of one of your series, with the replays",
    "options": [
        {
            "type": 4,
            "name": "series",
            "description": "One of your series this season",
            "required": True,
            "autocomplete": True,
        },
        {
            "type": 4,
            "name": "player1_score",
            "description": "Maps won by the first player",
            "required": True,
            "min_value": 0,
            "max_value": 3,
        },
        {
            "type": 4,
            "name": "player2_score",
            "description": "Maps won by the second player",
            "required": True,
            "min_value": 0,
            "max_value": 3,
        },
        {
            "type": ATTACHMENT,
            "name": "game1",
            "description": "The replay of game 1",
            "required": True,
        },
        {
            "type": ATTACHMENT,
            "name": "game2",
            "description": "The replay of game 2",
            "required": True,
        },
        {
            "type": ATTACHMENT,
            "name": "game3",
            "description": "The replay of game 3, when it was played",
        },
    ],
}


def _attachments(
    payload: dict[str, Any], options: dict[str, Any]
) -> list[dict[str, Any]]:
    """The files given as game1, game2, game3, in that order."""
    resolved = payload.get("data", {}).get("resolved", {}).get("attachments", {})
    return [
        resolved[options[name]]
        for name in ("game1", "game2", "game3")
        if options.get(name) in resolved
    ]


def _store(attachment: dict[str, Any], series_id: int, game_no: int) -> bool:
    """Move one file from Discord to the bucket, through the presigned link."""
    try:
        got = requests.get(attachment["url"], timeout=discord.REQUEST_TIMEOUT)
        got.raise_for_status()
        put = requests.put(
            replays.upload_url(series_id, game_no),
            data=got.content,
            timeout=discord.REQUEST_TIMEOUT,
        )
        put.raise_for_status()
    except requests.RequestException:
        return False
    return True


def _name(player: UserPublic | None) -> str:
    return (player.name if player else None) or "?"


def _refused(text: str) -> tuple[dict[str, Any], bool]:
    """A private red card: the reason, and that nothing was saved."""
    return {
        "embeds": [
            {
                "title": "Error · result not saved",
                "description": text,
                "color": 0xED4245,
            }
        ]
    }, PRIVATE


def _veto_warning(series_id: int) -> str:
    """The result stands, and the veto still belongs with it."""
    site = (os.getenv("FRONTEND_URL") or "").rstrip("/")
    board = (
        f"[veto board]({site}/player-series/{series_id}/veto)"
        if site
        else "veto board on the website"
    )
    return (
        f"The map veto of this series is not complete. The result is saved, and a"
        f" veto belongs with it: enter it on the {board}."
    )


def run(payload: dict[str, Any], services: Services) -> tuple[dict[str, Any], bool]:
    """/score series player1_score player2_score game1 game2 game3."""
    options = options_of(payload)
    series_id = int(options["series"])
    if series_id not in {row.id for row in own_series(payload, services)}:
        return _refused("Only a player of the series can report its result.")
    p1, p2 = int(options["player1_score"]), int(options["player2_score"])
    attached = _attachments(payload, options)
    if len(attached) != p1 + p2:
        games = p1 + p2
        return _refused(
            f"Attach one replay per game played: a {p1}-{p2} result needs {games} files,"
            f" game1 to game{games}. The score is saved only when the replays match it."
        )
    for game_no, attachment in enumerate(attached, 1):
        if attachment.get("size", 0) > MAX_BYTES:
            return _refused(f"Replay {game_no} is over 10 MB.")
        if not _store(attachment, series_id, game_no):
            return _refused(f"Replay {game_no} could not be stored. Try again.")

    discord_id, discord_tag = caller(payload)
    try:
        result = player_series.update_player_series(
            series_id,
            {"player1_score": p1, "player2_score": p2},
            discord_id=discord_id,
            discord_tag=discord_tag,
            user_service=services.users,
            series_service=services.series,
        )
    except BadRequestError as error:
        # what the replay check refuses, such as a file that is not a replay
        return _refused(str(error))
    if isinstance(result, JSONResponse):
        error = json.loads(bytes(result.body))["error"]
        return _refused(error)

    series = services.series.get(series_id)
    match = series.match
    round_no = match.playday if match else "?"
    result_line = (
        f"Result by <@{discord_id}>: {_name(series.player1)} {p1}-{p2}"
        f" {_name(series.player2)} · Round {round_no}"
    )
    lines = [result_line]
    lines += [f"Game {row['game_no']}: {row['url']}" for row in result["replays"]]
    if not result.get("veto_complete", True):
        lines.append(_veto_warning(series_id))
    return {"content": "\n".join(lines)}, PUBLIC
