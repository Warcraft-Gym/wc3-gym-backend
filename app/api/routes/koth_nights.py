"""The KOTH night routes: open a night, close it, take a Twitch signup.

A night is an event of the KOTH league, so every read is an event read and
these three writes are all the KOTH module owns.
"""

from typing import Any

from fastapi import APIRouter, Depends

from app.api.deps import SettingsServiceDep, require_admin
from app.models.koth_night import NightOpen
from app.models.season import EventPublic
from app.services.koth_night import night, nightbot

router = APIRouter(tags=["koth"])


@router.post("/koth/nights", status_code=201, dependencies=[Depends(require_admin)])
def open_night(data: NightOpen) -> EventPublic:
    """Open tonight's night: the event, its koth stage and its three brackets."""
    return night.open_night(data)


@router.post("/koth/nights/{night_id}/close", dependencies=[Depends(require_admin)])
def close_night(night_id: int) -> EventPublic:
    """Close the night: the unplayed series go, so every series left is scored."""
    return night.close_night(night_id)


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
