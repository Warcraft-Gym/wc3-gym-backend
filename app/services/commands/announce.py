"""/announce: the match card of one series, posted in the channel."""

from typing import Any

from app.models.series import SeriesPublic
from app.services.commands.base import (
    PRIVATE,
    PUBLIC,
    Services,
    cast_link,
    series_title,
)
from app.services.commands.veto import (
    SERIES_OPTION,
    board_link,
    picked,
    ping,
    state,
)

COMMAND: dict[str, Any] = {
    "name": "announce",
    "description": "Post the match card of one of your series",
    "options": [SERIES_OPTION],
}


def card(series: SeriesPublic) -> dict[str, Any]:
    """An embed with the time, the caster and the veto."""
    title = series_title(series)
    stamp = int(series.date_time.timestamp()) if series.date_time else None
    lines = [f"<t:{stamp}:F> (<t:{stamp}:R>)" if stamp else "Not scheduled yet"]
    lines += [f"Cast on {cast_link(cast.channel_url)}" for cast in series.casts]
    lines += [state(series), board_link(series.id)]
    return {
        "content": f"{ping(series.player1)} vs {ping(series.player2)}",
        "embeds": [
            {"title": title, "description": "\n".join(lines), "color": 0x4A4DB8}
        ],
    }


def run(payload: dict[str, Any], services: Services) -> tuple[dict[str, Any], bool]:
    """/announce series: the match card, posted in the channel."""
    series = picked(payload, services)
    if series is None:
        return {"content": "not_authorized_for_this_series"}, PRIVATE
    return card(series), PUBLIC
