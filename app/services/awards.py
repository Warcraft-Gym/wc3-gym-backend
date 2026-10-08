"""What an event hands out when it closes.

Closing an event freezes the table of its last stage into `event_award`: one
row per placed entrant of every division, so a trophy read lists a cup win or
a KOTH crown without replaying the stage. The write is the whole list, so
closing an event twice rewrites its places and never doubles them.
"""

from sqlalchemy import delete, select
from sqlalchemy.orm import Session as OrmSession
from sqlmodel import col

from app.core.db import Session
from app.core.exceptions import BadRequestError, NotFoundError
from app.models.base import ident
from app.models.event_award import EventAward, EventAwardPublic
from app.models.event_history import KothHistoryEvent
from app.models.event_stage import EventStage
from app.models.season import Season
from app.models.types import utcnow
from app.services import stage_engine

# The places that carry a name of their own; the rest are placed by number
TITLES = {1: "Champion", 2: "Runner-up", 3: "Third"}


def title_of(place: int) -> str:
    """The name of a place, which is what the award prints."""
    return TITLES.get(place, f"Placed {place}")


def close_event(session: OrmSession, event_id: int) -> list[EventAward]:
    """Write one award per placed entrant of the last stage, division by division.

    The last stage is the one the event ends on, so its table holds the places
    the event pays. The old rows go first, which makes a second close a rewrite.
    """
    if session.get(KothHistoryEvent, event_id) is not None:
        return list(
            session.scalars(
                select(EventAward).where(col(EventAward.event_id) == event_id)
            )
        )
    session.execute(delete(EventAward).where(col(EventAward.event_id) == event_id))
    stage = _last_stage(session, event_id)
    if stage is None:
        return []
    rows = [
        EventAward(
            event_id=event_id,
            entrant_id=line.entrant_id,
            user_id=line.user_id,
            team_id=line.team_id,
            place=line.position,
            title=title_of(line.position),
        )
        for table in stage_engine._tables(session, event_id, stage)
        for line in table.rows
    ]
    session.add_all(rows)
    session.flush()
    return rows


def finish(event_id: int) -> list[EventAwardPublic]:
    """Close the event and answer the places it paid, best place first.

    The close stamps `closed_at`, which is what makes the event read finished
    whatever results it still misses. A second close keeps the first stamp.
    """
    with Session.begin() as session:
        event = session.get(Season, event_id)
        if event is None:
            raise NotFoundError(f"Event not found by id: {event_id}")
        if event.cancelled_at is not None:
            raise BadRequestError("A cancelled event pays no place; reopen it first")
        if event.closed_at is None:
            event.closed_at = utcnow()
        rows = close_event(session, ident(event))
        return [EventAwardPublic.model_validate(row.model_dump()) for row in rows]


def reopen(event_id: int) -> None:
    """Take the close back: clear the stamp and the places it paid.

    The event reads by its series again, and the next close pays the places
    afresh. An archived event stays closed, its source results are the record.
    """
    with Session.begin() as session:
        event = session.get(Season, event_id)
        if event is None:
            raise NotFoundError(f"Event not found by id: {event_id}")
        if session.get(KothHistoryEvent, event_id) is not None:
            raise BadRequestError(
                "An archived event stays closed; its source results are preserved"
            )
        event.closed_at = None
        event.cancelled_at = None
        session.execute(delete(EventAward).where(col(EventAward.event_id) == event_id))


def cancel(event_id: int) -> None:
    """Call the event off: close it, stamp the cancel and pay no place.

    A cancelled event reads finished, its signups close with it, and a reopen
    takes the cancel back with the close.
    """
    with Session.begin() as session:
        event = session.get(Season, event_id)
        if event is None:
            raise NotFoundError(f"Event not found by id: {event_id}")
        now = utcnow()
        event.closed_at = event.closed_at or now
        event.cancelled_at = event.cancelled_at or now
        session.execute(delete(EventAward).where(col(EventAward.event_id) == event_id))


def _last_stage(session: OrmSession, event_id: int) -> EventStage | None:
    """The stage the event ends on; none when it holds no stage."""
    return session.scalars(
        select(EventStage)
        .where(col(EventStage.event_id) == event_id)
        .order_by(col(EventStage.position).desc())
    ).first()
