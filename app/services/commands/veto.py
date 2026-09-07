"""/veto: point the two players at the veto board and say where it stands.

The bot never runs a veto. Without a gateway there are no reactions to read,
so the board on the website is the only place a step is taken.
"""

import os
from typing import Any

from app.core.db import Session
from app.models.map import Map
from app.models.series import SeriesPublic
from app.models.user import UserPublic
from app.services.commands.base import (
    PRIVATE,
    PUBLIC,
    Services,
    options_of,
    own_series,
    series_line,
)
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
    """The veto, a line per step: the fixed map, each ban and pick with who
    took it, and whose move it is until the veto is complete."""
    board = SeriesVetoService().board(series.id, None)
    names = {"A": series.player1, "B": series.player2}

    def name(side: str) -> str:
        player = names[side]
        return (player.name if player else None) or "?"

    lines = []
    if board.week_map_id:
        with Session() as session:
            fixed = session.get(Map, board.week_map_id)
        lines.append(f"Fixed map · {(fixed.shortname or fixed.name) if fixed else '?'}")
    lines += [
        f"{step.action.title()} · {step.shortname or step.name} · {name(step.side)}"
        for step in board.steps
    ]
    if board.complete:
        return "\n".join(["veto complete", *lines])
    action, _, side = board.order[len(board.steps)].partition("_")
    turn = f"{name(side.upper())} to {action.lower()}"
    return "\n".join([f"veto {len(board.steps)}/{len(board.order)}, {turn}", *lines])


def card(series: SeriesPublic) -> dict[str, Any]:
    """The series, both players and where the veto stands."""
    return {
        "content": f"{series_line(series)}\n"
        f"{ping(series.player1)} vs {ping(series.player2)} · {state(series)}\n"
        f"{board_link(series.id)}"
    }


def run(payload: dict[str, Any], services: Services) -> tuple[dict[str, Any], bool]:
    """/veto series: the series, both players and where the veto stands."""
    series = picked(payload, services)
    if series is None:
        return {"content": "not_authorized_for_this_series"}, PRIVATE
    return card(series), PUBLIC
