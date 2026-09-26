"""One signup rule for every door of a KOTH night.

The battle tag is the identity and the rating comes from W3Champions alone: a
tag the app holds no fresh rating for is asked for once, under a timeout short
enough for a chat answer. A rating cuts the row into its bracket and puts it at
the end of that bracket's line; nothing found leaves the row unplaced, and the
signup stands either way for an admin to place by hand.
"""

import logging

from app.core.db import Session
from app.core.exceptions import ExternalServiceError
from app.models.base import ident
from app.models.enums import EventKind, Race
from app.models.event_entrant import EventEntrant, EventEntrantPublic
from app.models.season import Season
from app.models.types import utcnow
from app.models.user import User, UserReduced
from app.services import stage_engine
from app.services.events import (
    EventService,
    _end_seed,
    _entrant_publics,
    _event,
    _live_entrants,
    _stats_for,
)
from app.services.koth.night import divisions_of
from app.services.settings import SettingsService
from app.services.users import UserService
from app.services.w3c_stats import w3c_season

logger = logging.getLogger(__name__)

# A chat bot drops a slow answer, so this path waits five seconds, not ten
SYNC_TIMEOUT = 5.0

# How many seconds a tag the app already asked about waits for the next ask
SYNC_AGAIN = 3600


def follow(
    event_id: int, entrant_id: int, synced: bool = False
) -> EventEntrantPublic | None:
    """Cut the night into its brackets and seed at the end what the cut moved.

    A row the cut leaves where it stands keeps its place in the line, so a
    repeated signup costs a player nothing.

    The answer is the row as the door reads it back, or nothing when the event
    is no KOTH night: that is what lets the shared doors call this blind. A
    door that already asked W3Champions for this player passes `synced`, so
    the tag is asked about once per signup.
    """
    with Session.begin() as session:
        night = session.get(Season, event_id)
        row = session.get(EventEntrant, entrant_id)
        if night is None or night.kind is not EventKind.koth or row is None:
            return None
        if not divisions_of(session, event_id):
            # A night with no bracket cuts nothing; the row waits unplaced
            return None
        user = session.get(User, row.user_id) if row.user_id else None
        ask = (
            not synced
            and user is not None
            and unrated(user, row.race, w3c_season(session))
        )
        tag = (user.battleTag or "") if user is not None else ""
        user_id = ident(user) if user is not None else 0
    if ask and tag:
        sync_rating(user_id, tag)
    recut(event_id)
    with Session.begin() as session:
        row = session.get(EventEntrant, entrant_id)
        if row is None:
            return None
        return _entrant_publics(session, _event(session, event_id), [row])[0]


def recut(event_id: int) -> None:
    """Cut the rows no admin placed into the brackets as they now stand.

    A row the cut leaves where it is keeps its place in the line. A row the
    cut moves takes the end of its new line and leaves the throne it wore,
    because a crown never travels between brackets.
    """
    with Session.begin() as session:
        before = {
            ident(one): one.division_id for one in _live_entrants(session, event_id)
        }
    EventService().assign_divisions(event_id)
    with Session.begin() as session:
        rows = _live_entrants(session, event_id)
        moved = [one for one in rows if one.division_id != before.get(ident(one))]
        # Every row the cut moved into a bracket takes the end of that line
        for one in rows:
            if one.division_id is None:
                one.seed = None
            elif one.division_id != before.get(ident(one)) or one.seed is None:
                one.seed = _end_seed(session, event_id, one.division_id, ident(one))
        stage_engine.uncrown(session, [ident(one) for one in moved])
        session.flush()


def unrated(user: User, race: Race | None, season: int) -> bool:
    """Whether W3Champions gave this player no rating the cut can read.

    A signup that names no race asks for any rating inside the window, so a
    player rated on one race alone still signs up on that race.
    """
    races = (
        [race]
        if race is not None
        else [stat.race for stat in (user.w3c_stats or []) if stat.race is not None]
    )
    return all(_stats_for(user, one, season)[0] is None for one in races)


def sync_rating(user_id: int, battle_tag: str) -> None:
    """Ask W3Champions once for this tag; a refused ask leaves the row unplaced.

    A tag the app asked about in the last hour is not asked about again, so a
    repeated signup of a player w3champions does not know sends no traffic.
    """
    with Session.begin() as session:
        user = session.get(User, user_id)
        asked = user.w3c_synced_at if user is not None else None
        if asked is not None and (utcnow() - asked).total_seconds() < SYNC_AGAIN:
            return
    try:
        UserService(settings_app_service=SettingsService()).update_w3c_stats(
            UserReduced(id=user_id, battleTag=battle_tag), timeout=SYNC_TIMEOUT
        )
    except ExternalServiceError as error:
        logger.info(f"No W3Champions rating for a KOTH signup: {error}")
