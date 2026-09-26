"""The Twitch signup: one chat command enters one battle tag in tonight's night.

Nightbot cannot send a body, so the command is a GET carrying the shared
token. The signup itself is the shared entrant write under the `anyone`
policy; only the reply sentence is KOTH's own. A night takes one entry per
race, so a command naming a second race enters it beside the first.
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
from app.models.event_entrant import EntrantAdd, EventEntrant
from app.models.season import Season
from app.models.user import User
from app.services.events import (
    EventService,
    _by_battle_tag,
    _stats_for,
)
from app.services.koth.night import taking_signups
from app.services.koth.signup import follow, sync_rating, unrated
from app.services.w3c_stats import w3c_season

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
    with Session.begin() as session:
        event_id = ident(taking_signups(session))
    chosen = enter(event_id, battletag, race)

    with Session.begin() as session:
        user = _by_battle_tag(session, battletag, chosen)
        row = _entrant(session, event_id, ident(user), chosen)
        division = (
            session.get(EventDivision, row.division_id)
            if row and row.division_id
            else None
        )
        bracket = division.name if division is not None else None
        mmr = _stats_for(user, chosen, w3c_season(session))[0]
        tag = user.battleTag or battletag
    if bracket is None:
        return {
            "success": True,
            "message": (
                f"{twitch} is signed up; W3Champions gave no rating for {tag}"
                " yet, the admin places you"
            ),
        }
    rating = f" ({mmr} MMR)" if mmr is not None else ""
    return {
        "success": True,
        "message": f"{twitch} signed up for {bracket}{rating}",
    }


def enter(
    event_id: int,
    battle_tag: str,
    race: str | None,
    channel: SignupChannel = SignupChannel.twitch,
) -> Race:
    """Enter one battle tag in a night; answer the race he plays.

    A night that takes one entry per race holds a row per race: the command
    reopens the row of the race it names, or adds one. Any other event holds
    one row per player and the command replaces its race and its bracket. A
    player w3champions carries no rating for enters unplaced.
    """
    named = _race(race)
    with Session.begin() as session:
        user = _by_battle_tag(session, battle_tag, named or Race.RANDOM)
        user_id = ident(user)
        tag = user.battleTag or battle_tag
        ask = unrated(user, named, w3c_season(session))
    if ask:
        sync_rating(user_id, tag)

    with Session.begin() as session:
        user = session.get(User, user_id)
        chosen = named or (
            _best_race(user, w3c_season(session)) if user is not None else Race.RANDOM
        )
        night = session.get(Season, event_id)
        per_race = chosen if night is not None and night.multi_entry else None
        row = _entrant(session, event_id, user_id, per_race)
        entered = row is not None
        entrant_id = ident(row) if row is not None else 0
        if row is not None:
            row.race = chosen
            if row.withdrawn_at is not None:
                # A player who left and comes back stands at the end again
                row.withdrawn_at = None
                row.seed = None

    if entered:
        # The row stood already, so the rule runs over it here
        follow(event_id, entrant_id, synced=True)
    else:
        EventService().add_entrant_as_admin(
            event_id,
            EntrantAdd(
                race=chosen,
                battle_tag=battle_tag,
                user_id=user_id,
                channel=channel,
            ),
            synced=True,
        )
    return chosen


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


def _best_race(user: User, season: int) -> Race:
    """The race a command that names none plays: his best rating in the window.

    The window is the one the signup checks the rating against, so the race
    picked is one that can pass the check: a stale rating never pins the race.
    """
    rated = {
        stat.race: _stats_for(user, stat.race, season)[0]
        for stat in (user.w3c_stats or [])
        if stat.race is not None
    }
    playing = {race: mmr for race, mmr in rated.items() if mmr is not None}
    if playing:
        return max(playing, key=lambda race: (playing[race], race.value))
    return user.race or Race.RANDOM


def _entrant(
    session: OrmSession, event_id: int, user_id: int, race: Race | None = None
) -> EventEntrant | None:
    """The row this player holds in the night, or the one he holds on a race."""
    statement = select(EventEntrant).where(
        col(EventEntrant.event_id) == event_id,
        col(EventEntrant.user_id) == user_id,
    )
    if race is not None:
        statement = statement.where(col(EventEntrant.race) == race)
    return session.scalars(statement).first()
