"""One signup rule for every door of a KOTH night.

The battle tag is the identity and the rating comes from W3Champions alone:
every signup asks for it, at most once an hour per tag, under a timeout short
enough for a chat answer. A rating cuts the row into its bracket and puts it at
the end of that bracket's line, and the row stays there until a bounds save;
nothing found leaves the row unplaced, and the signup stands either way for an
admin to place by hand.
"""

import logging
from collections.abc import Sequence

from sqlalchemy import or_, select
from sqlalchemy.orm import Session as OrmSession
from sqlmodel import col

from app.core.db import Session
from app.core.divisions import cut
from app.core.exceptions import ExternalServiceError
from app.models.base import ident
from app.models.enums import EventKind
from app.models.event_entrant import EventEntrant, EventEntrantPublic
from app.models.season import Season
from app.models.types import utcnow
from app.models.user import User, UserReduced
from app.services import stage_engine
from app.services.events import (
    _end_seed,
    _entrant_publics,
    _event,
    _live_entrants,
    _mmrs,
)
from app.services.koth.night import divisions_of, series_of
from app.services.settings import SettingsService
from app.services.users import UserService

logger = logging.getLogger(__name__)

# A chat bot drops a slow answer, so this path waits five seconds, not ten
SYNC_TIMEOUT = 5.0

# How many seconds a tag the app already asked about waits for the next ask
SYNC_AGAIN = 3600


def follow(
    event_id: int, entrant_id: int, synced: bool = False
) -> EventEntrantPublic | None:
    """Cut the rows no bracket holds yet and seed them at the end of their line.

    A placed row keeps its bracket and its place in the line, so a signup
    moves no other row and a repeated signup costs a player nothing.

    The answer is the row as the door reads it back, or nothing when the event
    is no KOTH night or a closed one: that is what lets the shared doors call
    this blind. A door that already asked W3Champions for this player passes
    `synced`, so the tag is asked about once per signup.
    """
    with Session.begin() as session:
        night = session.get(Season, event_id)
        row = session.get(EventEntrant, entrant_id)
        if night is None or night.kind is not EventKind.koth or row is None:
            return None
        if night.closed_at is not None:
            # A closed night keeps its rows and crowns as the close left them
            return None
        if not divisions_of(session, event_id):
            # A night with no bracket cuts nothing; the row waits unplaced
            return None
        user = session.get(User, row.user_id) if row.user_id else None
        ask = not synced and user is not None
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


def recut(event_id: int, bounds: bool = False) -> None:
    """Cut the rows of a night into its brackets, in one transaction.

    A signup cuts only the rows no bracket holds, so a placed row stays where
    it stands. A bounds save cuts every row by the rating stored when it was
    cut, the rows that left among them, but not a side of a series on the
    table. No cut moves a row an admin placed by hand, and a row with no
    rating is never cut. A moved row takes the end of its new line and leaves
    the throne it wore. A closed night is never cut.
    """
    with Session.begin() as session:
        night = session.get(Season, event_id)
        brackets = divisions_of(session, event_id)
        if night is None or night.closed_at is not None or not brackets:
            return
        rows = _night_rows(session, event_id, bounds)
        cuttable = [row for row in rows if not row.manual_placement]
        _store_ratings(session, cuttable)
        held = (
            {
                entrant_id
                for series in series_of(session, event_id)
                if not stage_engine.scored(series)
                for entrant_id in (series.entrant1_id, series.entrant2_id)
            }
            if bounds
            else set()
        )
        movable = [
            row
            for row in cuttable
            if row.mmr_at_seed is not None
            and ident(row) not in held
            and (bounds or row.division_id is None)
        ]
        # A night cuts by bound alone; its brackets name no size
        bands = cut(
            [(ident(row), row.mmr_at_seed) for row in movable],
            [(bracket.lower_bound, None) for bracket in brackets],
        )
        moved = []
        for row in movable:
            band = bands.get(ident(row))
            target = None if band is None else ident(brackets[band])
            if target != row.division_id:
                row.division_id = target
                row.seed = None
                moved.append(ident(row))
        # A row in a bracket with no place, moved or come back, stands last
        for row in rows:
            if row.division_id is not None and row.seed is None:
                row.seed = _end_seed(session, event_id, row.division_id, ident(row))
        stage_engine.uncrown(session, moved)
        session.flush()


def _night_rows(session: OrmSession, event_id: int, bounds: bool) -> list[EventEntrant]:
    """The rows a cut reads: the live rows, and at a bounds save the placed rows that left."""
    if not bounds:
        return _live_entrants(session, event_id)
    return list(
        session.scalars(
            select(EventEntrant)
            .where(
                col(EventEntrant.event_id) == event_id,
                or_(
                    col(EventEntrant.withdrawn_at).is_(None),
                    col(EventEntrant.division_id).is_not(None),
                ),
            )
            .order_by(col(EventEntrant.id))
        )
    )


def _store_ratings(session: OrmSession, rows: Sequence[EventEntrant]) -> None:
    """Store the live rating of every row that holds no cut rating yet."""
    bare = [row for row in rows if row.mmr_at_seed is None]
    if not bare:
        return
    ratings = _mmrs(session, bare)
    for row in bare:
        row.mmr_at_seed = ratings[ident(row)]


def sync_rating(user_id: int, battle_tag: str) -> None:
    """Ask W3Champions once for this tag; a refused ask leaves the row unplaced.

    Every signup asks, so the cut reads the rating of today and not of the last
    sync. A tag the app asked about in the last hour is not asked about again,
    so a repeated signup sends no traffic.
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
