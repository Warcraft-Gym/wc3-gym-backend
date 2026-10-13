"""What an event hands out when it closes.

Closing an event freezes the table of its last stage into `event_award`: one
row per placed entrant of every division, so a trophy read lists a cup win or
a KOTH crown without replaying the stage. The write is the whole list, so
closing an event twice rewrites its places and never doubles them.
"""

from collections.abc import Collection

from sqlalchemy import delete, select
from sqlalchemy.orm import Session as OrmSession
from sqlmodel import col

from app.core.db import Session
from app.core.exceptions import BadRequestError, NotFoundError
from app.models.base import ident
from app.models.enums import EventKind
from app.models.event_award import EventAward, EventAwardPublic
from app.models.event_history import KothHistoryEvent
from app.models.event_stage import EventStage, StandingRow
from app.models.season import Season
from app.models.types import utcnow
from app.services import cup_engine, stage_engine

# The places that carry a name of their own; the rest are placed by number
TITLES = {1: "Champion", 2: "Runner-up", 3: "Third"}


def title_of(place: int) -> str:
    """The name of a place, which is what the award prints."""
    return TITLES.get(place, f"Placed {place}")


def close_event(session: OrmSession, event_id: int) -> list[EventAward]:
    """Write one award per placed entrant, division by division.

    The last stage is the one the event ends on, so its table holds the first
    places; an entrant a playoff left out takes the next place in the order of
    the stage before it. The old rows go first, which makes a second close a
    rewrite.
    """
    if session.get(KothHistoryEvent, event_id) is not None:
        return list(
            session.scalars(
                select(EventAward).where(col(EventAward.event_id) == event_id)
            )
        )
    session.execute(delete(EventAward).where(col(EventAward.event_id) == event_id))
    # A cup played over rounds pays the places of its overall table
    from app.services import cup_rounds

    if cup_rounds.has_legs(session, event_id):
        rows = [
            EventAward(
                event_id=event_id,
                entrant_id=row.entrant_id,
                user_id=row.user.id if row.user else None,
                place=row.position,
                title=title_of(row.position),
            )
            for row in cup_rounds.overall_rows(session, event_id)
            if row.legs
        ]
        session.add_all(rows)
        session.flush()
        return rows
    # A cup team is no league team: its award names it through the entrant
    cup = _is_cup(session, event_id)
    rows = [
        EventAward(
            event_id=event_id,
            entrant_id=line.entrant_id,
            user_id=line.user_id,
            team_id=None if cup else line.team_id,
            place=place,
            title=title_of(place),
        )
        for place, line in event_places(session, event_id)
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


def event_places(
    session: OrmSession, event_id: int, stage_ids: Collection[int] | None = None
) -> list[tuple[int, StandingRow]]:
    """Every placed entrant of the event with its place, best first.

    The stages are read from the last one back: the last stage places its own
    entrants as its table stands, a shared place staying shared, and each
    stage before it places the entrants no later stage played, after all of
    those, in its own order. Divisions place apart, each from place one.
    `stage_ids` names the stages to read, which is how one round of a cup is
    placed on its own; left out, every stage of the event is read.
    """
    stages = session.scalars(
        select(EventStage)
        .where(
            col(EventStage.event_id) == event_id,
            *([col(EventStage.id).in_(stage_ids)] if stage_ids is not None else []),
        )
        .order_by(col(EventStage.position).desc())
    ).all()
    placed: dict[int | None, list[tuple[int, StandingRow]]] = {}
    seen: set[int] = set()
    # A cup ranks on its own tables, a KOTH night on the series it played
    tables = cup_engine.tables if _is_cup(session, event_id) else stage_engine.tables
    for index, stage in enumerate(stages):
        for table in tables(session, event_id, stage):
            lines = placed.setdefault(table.division_id, [])
            fresh = [line for line in table.rows if line.entrant_id not in seen]
            if index == 0:
                lines += [(line.position, line) for line in fresh]
            else:
                lines += [
                    (len(lines) + number, line)
                    for number, line in enumerate(fresh, start=1)
                ]
            seen |= {line.entrant_id for line in fresh}
    return [pair for lines in placed.values() for pair in lines]


def _is_cup(session: OrmSession, event_id: int) -> bool:
    event = session.get(Season, event_id)
    return event is not None and event.kind is EventKind.cup
