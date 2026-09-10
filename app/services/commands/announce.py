"""/announce: the match card of one series, posted in the channel."""

from typing import Any

from app.models.series import SeriesPublic
from app.services import series_cards
from app.services.commands.base import PRIVATE, PUBLIC, Services
from app.services.commands.veto import SERIES_OPTION, picked, ping

COMMAND: dict[str, Any] = {
    "name": "announce",
    "description": "Post the match card of one of your series",
    "options": [SERIES_OPTION],
}


def card(series: SeriesPublic) -> dict[str, Any]:
    """The match card, both players tagged: a player posts it to call the other."""
    return {
        "content": f"{ping(series.player1)} vs {ping(series.player2)}",
        "embeds": [series_cards.match_embed(series)],
    }


def run(payload: dict[str, Any], services: Services) -> tuple[dict[str, Any], bool]:
    """/announce series: the match card, posted in the channel."""
    series = picked(payload, services)
    if series is None:
        return {"content": "not_authorized_for_this_series"}, PRIVATE
    return card(series), PUBLIC
