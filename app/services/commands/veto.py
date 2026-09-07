"""/veto: point the two players at the veto board and say where it stands.

The bot never runs a veto. Without a gateway there are no reactions to read,
so the board on the website is the only place a step is taken.
"""

import os
from typing import Any

from app.core.db import Session
from app.models.series import Series, SeriesPublic
from app.models.user import UserPublic
from app.services import discord
from app.services.interactions import (
    PRIVATE,
    PUBLIC,
    Services,
    _series_line,
    options_of,
    own_series,
)
from app.services.series import SeriesService
from app.services.series_veto import SeriesVetoService

# Both commands take the same option: a series of the caller, by autocomplete
SERIES_OPTION = {
    "type": 4,
    "name": "series",
    "description": "One of your series this season",
    "required": True,
    "autocomplete": True,
}

COMMAND: dict[str, Any] = {
    "name": "veto",
    "description": "Where the map veto of one of your series stands",
    "options": [SERIES_OPTION],
}


def picked(payload: dict[str, Any], services: Services) -> SeriesPublic | None:
    """The series the `series` option names, if the caller plays it."""
    series_id = int(options_of(payload)["series"])
    return next(
        (row for row in own_series(payload, services) if row.id == series_id), None
    )


def ping(player: UserPublic | None) -> str:
    """The player pinged, or their name when the account has no Discord id."""
    if player and player.discordId:
        return f"<@{player.discordId}>"
    return (player.name if player else None) or "?"


def board_link(series_id: int) -> str:
    """The board on the site; the site signs the member in through Discord."""
    site = os.getenv("FRONTEND_URL")
    if not site:
        return "The veto board is on the website."
    return f"{site.rstrip('/')}/player-series/{series_id}/veto"


def state(series: SeriesPublic) -> str:
    """The veto in one phrase: complete, or the steps taken and whose turn it is."""
    service = SeriesVetoService()
    if service.is_complete(series.id):
        return "veto complete"
    board = service.board(series.id, None)
    step = board.order[len(board.steps)]
    on_turn = series.player1 if step.upper().endswith("_A") else series.player2
    name = (on_turn.name if on_turn else None) or "?"
    return f"veto {len(board.steps)}/{len(board.order)}, {name} to move"


def card(series: SeriesPublic) -> dict[str, Any]:
    """The series, both players and where the veto stands."""
    return {
        "content": f"{_series_line(series)}\n"
        f"{ping(series.player1)} vs {ping(series.player2)} · {state(series)}\n"
        f"{board_link(series.id)}"
    }


def run(payload: dict[str, Any], services: Services) -> tuple[dict[str, Any], bool]:
    """/veto series: the series, both players and where the veto stands."""
    series = picked(payload, services)
    if series is None:
        return {"content": "not_authorized_for_this_series"}, PRIVATE
    return card(series), PUBLIC


def remember_post(
    series_id: int, command: str, channel_id: str, message_id: str
) -> None:
    """Keep the bot's post of the series, so a veto step can edit it. The
    newest post replaces the last one."""
    with Session.begin() as session:
        series = session.get(Series, series_id)
        if series:
            series.discord_post_command = command
            series.discord_post_channel_id = channel_id
            series.discord_post_message_id = message_id


def refresh_post(series_id: int) -> None:
    """Rebuild the bot's last post of the series, if there is one, so its
    veto line says where the veto stands now."""
    from app.services.commands import announce  # imports this module

    with Session() as session:
        series = session.get(Series, series_id)
        if not series:
            return
        command = series.discord_post_command
        channel_id = series.discord_post_channel_id
        message_id = series.discord_post_message_id
    if not command or not channel_id or not message_id:
        return
    build = {"veto": card, "announce": announce.card}[command]
    discord.edit_channel_message(
        channel_id, message_id, build(SeriesService().get(series_id))
    )
