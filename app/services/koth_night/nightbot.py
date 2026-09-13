"""The Twitch signup: one chat command enters one battle tag in tonight's night.

Nightbot cannot send a body, so the command is a GET carrying the shared
token. The signup itself is the shared entrant write under the `anyone`
policy; only the reply sentence and the one-entrant-per-night rule are KOTH's
own. A second signup by the same player replaces his race and his bracket.
"""

from typing import TYPE_CHECKING, Any

from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession
from sqlmodel import col

from app.core.db import Session
from app.core.exceptions import ApiError, BadRequestError, NotFoundError
from app.models.base import ident
from app.models.enums import Race, SignupChannel
from app.models.event_division import EventDivision
from app.models.event_entrant import EntrantSignup, EventEntrant
from app.models.user import User
from app.services.events import (
    SEASONS,
    EventService,
    _by_battle_tag,
    _stats_for,
    _w3c_season,
)
from app.services.koth_night import carry
from app.services.koth_night.night import tonight

if TYPE_CHECKING:
    from app.services.settings import SettingsService

RACES = "orc, human, undead, nightelf, random"


def signup(
    settings: "SettingsService",
    token: str | None,
    twitch: str | None,
    battletag: str | None,
    race: str | None,
) -> dict[str, Any]:
    """Enter the battle tag in tonight's night and answer the line chat reads."""
    _check_token(settings, token)
    if not twitch or not battletag:
        raise BadRequestError("Missing required parameters: token, twitch, battletag")
    named = _race(race)

    with Session.begin() as session:
        event_id = ident(tonight(session))
        user = _by_battle_tag(session, battletag, named or Race.RANDOM)
        chosen = named or _best_race(user)
        # A player with no current rating has no bracket, so nothing is written
        if _stats_for(user, chosen, _w3c_season(session))[0] is None:
            raise BadRequestError(_no_rating(battletag, race))
        row = _entrant(session, event_id, ident(user))
        entered = row is not None
        if row is not None:
            row.race = chosen
            row.withdrawn_at = None

    if not entered:
        EventService().add_entrant(
            event_id,
            EntrantSignup(
                race=chosen, battle_tag=battletag, channel=SignupChannel.twitch
            ),
            claims=None,
        )
    EventService().assign_divisions(event_id)
    carry.follow_signup(event_id)

    with Session.begin() as session:
        user = _by_battle_tag(session, battletag, chosen)
        row = _entrant(session, event_id, ident(user))
        division = (
            session.get(EventDivision, row.division_id)
            if row and row.division_id
            else None
        )
        bracket = division.name if division else "no bracket"
        mmr = _stats_for(user, chosen, _w3c_season(session))[0]
    return {
        "success": True,
        "message": f"{twitch} signed up for {bracket} ({mmr} MMR)",
    }


def _check_token(settings: "SettingsService", token: str | None) -> None:
    """401 unless the caller carries the Nightbot token (chat bots, not admins)."""
    try:
        expected = settings.get_by_key("KOTH_NIGHTBOT_TOKEN").value
    except NotFoundError:
        # a deployment that never generated a token refuses every caller
        expected = None
    if not expected or str(token) != str(expected):
        raise ApiError(401, {"error": "Unauthorized - invalid client token"})


def _race(race: str | None) -> Race | None:
    """The race the command names; a command that names none picks it later."""
    if not race:
        return None
    try:
        return Race.from_text(race)
    except ValueError as error:
        raise BadRequestError(
            f"Invalid race '{race}'. Valid options: {RACES}"
        ) from error


def _no_rating(battle_tag: str, race: str | None) -> str:
    """What chat reads when the player carries no rating the night can cut on."""
    if race:
        return (
            f"No W3Champions statistics found for {battle_tag} with race"
            f" {race} in the last {SEASONS} seasons"
        )
    return f"No valid MMR data found for {battle_tag} in the last {SEASONS} seasons"


def _best_race(user: User) -> Race:
    """The race a command that names none plays: the player's best stored rating."""
    rated = [stat for stat in (user.w3c_stats or []) if stat.race and stat.mmr]
    best = max(rated, key=lambda stat: stat.mmr or 0, default=None)
    if best is not None and best.race is not None:
        return best.race
    return user.race or Race.RANDOM


def _entrant(session: OrmSession, event_id: int, user_id: int) -> EventEntrant | None:
    """The row this player already holds in the night; one per player per night."""
    return session.scalars(
        select(EventEntrant).where(
            col(EventEntrant.event_id) == event_id,
            col(EventEntrant.user_id) == user_id,
        )
    ).first()
