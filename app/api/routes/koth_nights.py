"""The KOTH night routes: open a night, run it live, close it, take a signup.

A night is an event of the KOTH league. An admin makes every series by hand
while the night runs, and each write answers the board, which is the one read
the run page and the public dashboard both draw.
"""

from typing import Any

from fastapi import APIRouter, Depends, Response

from app.api.deps import SettingsServiceDep, require_admin
from app.models.koth_night import (
    CrownWrite,
    KothBoard,
    NightOpen,
    QueueWrite,
    SeriesResult,
    SeriesStart,
)
from app.models.season import EventPublic
from app.services.koth import board, live, night, nightbot

router = APIRouter(tags=["koth"])


@router.post("/koth/nights", status_code=201, dependencies=[Depends(require_admin)])
def open_night(data: NightOpen) -> EventPublic:
    """Open tonight's night: the event, its koth stage and its three brackets."""
    return night.open_night(data)


@router.post("/koth/nights/{night_id}/close", dependencies=[Depends(require_admin)])
def close_night(night_id: int) -> EventPublic:
    """Close the night: the unplayed series go, so every series left is scored."""
    return night.close_night(night_id)


@router.post(
    "/koth/nights/{night_id}/series",
    status_code=201,
    dependencies=[Depends(require_admin)],
)
def start_series(night_id: int, data: SeriesStart) -> KothBoard:
    """Put two race rows of one bracket on the table as a best of one."""
    return live.start_series(night_id, data)


@router.delete(
    "/koth/nights/{night_id}/series/{series_id}",
    dependencies=[Depends(require_admin)],
)
def cancel_series(night_id: int, series_id: int) -> KothBoard:
    """Take an unplayed series off the table."""
    return live.cancel_series(night_id, series_id)


@router.put(
    "/koth/nights/{night_id}/series/{series_id}/result",
    dependencies=[Depends(require_admin)],
)
def set_result(night_id: int, series_id: int, data: SeriesResult) -> KothBoard:
    """Enter who won the one map, or turn a result of tonight around."""
    return live.set_result(night_id, series_id, data)


@router.put(
    "/koth/nights/{night_id}/brackets/{division_id}/queue",
    dependencies=[Depends(require_admin)],
)
def set_queue(night_id: int, division_id: int, data: QueueWrite) -> KothBoard:
    """Order one bracket's line; no other bracket moves."""
    return live.set_queue(night_id, division_id, data)


@router.put(
    "/koth/nights/{night_id}/brackets/{division_id}/crown",
    dependencies=[Depends(require_admin)],
)
def set_crown(night_id: int, division_id: int, data: CrownWrite) -> KothBoard:
    """Pass the crown of one bracket on, or empty its throne."""
    return live.set_crown(night_id, division_id, data)


@router.delete(
    "/koth/nights/{night_id}/entrants/{entrant_id}",
    dependencies=[Depends(require_admin)],
)
def remove_entrant(night_id: int, entrant_id: int) -> KothBoard:
    """Take a row out of tonight: it leaves the line, the throne and the table."""
    return live.remove_entrant(night_id, entrant_id)


@router.post(
    "/koth/nights/{night_id}/entrants/{entrant_id}/restore",
    dependencies=[Depends(require_admin)],
)
def restore_entrant(night_id: int, entrant_id: int) -> KothBoard:
    """Put a row that left back in; it stands at the end of the line."""
    return live.restore_entrant(night_id, entrant_id)


@router.get("/koth/board")
def get_tonight_board(response: Response) -> KothBoard:
    """The board of the night that takes signups."""
    return _board(response, None)


@router.get("/koth/nights/{night_id}/board")
def get_board(night_id: int, response: Response) -> KothBoard:
    """The whole night in one read: the header, the rows nobody placed yet, and
    every bracket with its king, its line and the series it played."""
    return _board(response, night_id)


def _board(response: Response, night_id: int | None) -> KothBoard:
    """The board, cached at the edge because the dashboard polls it."""
    # the dashboard polls every 30 seconds; the edge serves every viewer one read
    response.headers["Cache-Control"] = "public, s-maxage=15"
    # the edge keeps the headers of the request that filled it, and CORSMiddleware
    # writes none when that request has no Origin, so a browser reads a copy it blocks
    response.headers["Access-Control-Allow-Origin"] = "*"
    return board.read(night_id)


@router.get("/koth/signup")
def create_signup_nightbot(
    settings: SettingsServiceDep,
    token: str | None = None,
    twitch: str | None = None,
    battletag: str | None = None,
    race: str | None = None,
) -> dict[str, Any]:
    """Create a signup via URL parameters (Nightbot compatible).

    Usage: GET /koth/signup?token=KOTH_TOKEN&twitch=username&battletag=Name%231234
    """
    return nightbot.signup(settings, token, twitch, battletag, race)
