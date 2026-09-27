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
from app.core.exceptions import NotFoundError
from app.models.base import ident
from app.models.event_award import EventAward, EventAwardPublic
from app.models.event_history import KothHistoryEvent
from app.models.event_stage import EventStage
from app.models.season import Season
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
    """Close the event and answer the places it paid, best place first."""
    with Session.begin() as session:
        event = session.get(Season, event_id)
        if event is None:
            raise NotFoundError(f"Event not found by id: {event_id}")
        rows = close_event(session, ident(event))
        return [EventAwardPublic.model_validate(row.model_dump()) for row in rows]


def _last_stage(session: OrmSession, event_id: int) -> EventStage | None:
    """The stage the event ends on; none when it holds no stage."""
    return session.scalars(
        select(EventStage)
        .where(col(EventStage.event_id) == event_id)
        .order_by(col(EventStage.position).desc())
    ).first()
