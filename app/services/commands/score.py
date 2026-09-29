"""/report-result: report a result from Discord, with one replay per game played when it has them.

The attachments Discord holds are moved into the bucket through the same presigned
links the browser uses, then the result goes through the write the dashboard uses,
so the veto rule and the best-of rule are the same in both places.
"""

from typing import Any

import requests

from app.core.config import frontend_url
from app.core.exceptions import ApiError, BadRequestError, NotFoundError
from app.models.user import UserSummaryPublic
from app.services import discord, player_series, replays
from app.services.commands.base import (
    PRIVATE,
    Services,
    caller,
    options_of,
    own_series,
)

# What Discord accepts as an attachment option
ATTACHMENT = 11
MAX_BYTES = 10 * 1024 * 1024

COMMAND: dict[str, Any] = {
    "name": "report-result",
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
        },
        {
            "type": ATTACHMENT,
            "name": "game2",
            "description": "The replay of game 2",
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
) -> dict[int, dict[str, Any]]:
    """The files given as game1, game2, game3, by game number."""
    resolved = payload.get("data", {}).get("resolved", {}).get("attachments", {})
    return {
        game_no: resolved[options[f"game{game_no}"]]
        for game_no in (1, 2, 3)
        if options.get(f"game{game_no}") in resolved
    }


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


def _name(player: UserSummaryPublic | None) -> str:
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
    site = frontend_url()
    board = (
        f"[veto board]({site}/player-series/{series_id}/veto)"
        if site
        else "veto board on the website"
    )
    return (
        f"The map veto of this series is not complete. The result is saved, and a"
        f" veto belongs with it: enter it on the {board}."
    )


def _replay_warning(games: list[int]) -> str:
    """The result stands, and each game's replay still belongs with it."""
    listed = ", ".join(f"game {game}" for game in games)
    return (
        f"No replay saved for {listed}. The result is saved, and every game needs its"
        " replay: add it with Edit result on the website."
    )


def run(payload: dict[str, Any], services: Services) -> tuple[dict[str, Any], bool]:
    """/score series player1_score player2_score game1 game2 game3."""
    options = options_of(payload)
    series_id = int(options["series"])
    if series_id not in {row.id for row in own_series(payload, services)}:
        return _refused("Only a player of the series can report its result.")
    p1, p2 = int(options["player1_score"]), int(options["player2_score"])
    # A file that is too big or fails to store leaves its game without a replay; the
    # write lists those games and the reply warns
    for game_no, attachment in _attachments(payload, options).items():
        if game_no <= p1 + p2 and attachment.get("size", 0) <= MAX_BYTES:
            _store(attachment, series_id, game_no)

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
    except (ApiError, BadRequestError, NotFoundError) as error:
        # what the write refuses: an unknown series, someone else's, a score out of range
        return _refused(str(error))

    # The write posts the result card; a public reply here would repeat it
    series = services.series.get(series_id)
    score = f"{_name(series.player1)} {p1}-{p2} {_name(series.player2)}"
    lines = [f"Reported: {score}. The result card is in the results channel."]
    if result.get("replays_missing"):
        lines.append(_replay_warning(result["replays_missing"]))
    if not result.get("veto_complete", True):
        lines.append(_veto_warning(series_id))
    return {"content": "\n".join(lines)}, PRIVATE
