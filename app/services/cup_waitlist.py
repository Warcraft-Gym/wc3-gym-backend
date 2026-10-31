"""A cup's line: who of its sign-ups is in, and who waits on its waitlist.

Every entrant of a cup stands in its line, in the order it last signed up
(`cup_entrant_line`). The first places of the line are in and the rest wait;
`app.core.waitlist.places` says how many places there are. An entrant a
runner let in by hand stays in whatever its place, and counts in the line.

Until the cup is drawn the line moves both ways: a filled division lets its
waiting players in, and a withdrawal sends the players past the places back.
Once a cup over rounds holds a draw the line only moves forward, so nobody who
played a round loses their place to another player's withdrawal. A cup played
on one evening is set at its draw: a late sign-up waits, and a runner swaps it
in for a player who has not played.

Every waiting entrant may check in like an entrant that is in, so a runner can
let in one who did when a player does not show; the draw never seats one.
"""

from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession
from sqlmodel import col

from app.core.waitlist import places
from app.models.base import ident
from app.models.cup_settings import CupEntrantLine
from app.models.enums import EventKind
from app.models.event_entrant import EventEntrant
from app.models.season import Season
from app.models.types import utcnow
from app.services import cup_divisions, cup_rounds

DRAWN = (
    "The cup is drawn: swap them in for a player who has not played, "
    "or undo the draw first"
)


def is_set(session: OrmSession, event: Season) -> bool:
    """Whether the cup's field is set: a cup played on one evening is drawn.
    A cup over rounds takes players for its later rounds."""
    event_id = ident(event)
    return cup_divisions.drawn(session, event_id) and not cup_rounds.has_legs(
        session, event_id
    )


def join(
    session: OrmSession,
    event: Season,
    row: EventEntrant,
    held: bool = False,
    at: datetime | None = None,
) -> None:
    """Stand the entrant at the end of the cup's line, or at `at`, and settle
    the line. A runner's swap is `held` in at once; a sign-up or hand-add
    waits until the line lets it in."""
    when = at or utcnow()
    line = session.get(CupEntrantLine, ident(row))
    if line is None:
        session.add(CupEntrantLine(entrant_id=ident(row), joined_at=when, held_in=held))
    else:
        line.joined_at = when
        line.held_in = held
    row.waitlisted_at = None if held else when
    session.flush()
    settle(session, event)


def hold_in(session: OrmSession, row: EventEntrant) -> None:
    """Let one waiting entrant in by hand; the line never sends it back."""
    line = session.get(CupEntrantLine, ident(row))
    if line is None:
        session.add(
            CupEntrantLine(
                entrant_id=ident(row),
                joined_at=row.waitlisted_at or row.created_at,
                held_in=True,
            )
        )
    else:
        line.held_in = True
    row.waitlisted_at = None
    session.flush()


def joined_at(session: OrmSession, row: EventEntrant) -> datetime:
    """Where the entrant stands in the line."""
    line = session.get(CupEntrantLine, ident(row))
    return line.joined_at if line is not None else row.created_at


def take_place(session: OrmSession, row: EventEntrant) -> datetime:
    """Take the entrant out of the line before its row goes, and answer where
    it stood, so the entrant that replaces it stands there."""
    line = session.get(CupEntrantLine, ident(row))
    if line is None:
        return row.created_at
    session.delete(line)
    session.flush()
    return line.joined_at


def settle(session: OrmSession, event: Season) -> None:
    """Let in the entrants the line's places take, and on a cup not yet drawn
    put the rest on the waitlist; a cup that is set keeps its field."""
    if event.kind is not EventKind.cup or is_set(session, event):
        return
    forward = cup_divisions.drawn(session, ident(event))
    line = _line(session, ident(event))
    taken = places(
        len(line), event.entrant_cap, bool(cup_divisions.uses_divisions(session, event))
    )
    for index, (row, at, held) in enumerate(line):
        if index < taken or held:
            row.waitlisted_at = None
        elif not forward and row.waitlisted_at is None:
            # the waitlist reads in line order, so a player sent back keeps their place in it
            row.waitlisted_at = at
    session.flush()


def _line(
    session: OrmSession, event_id: int
) -> list[tuple[EventEntrant, datetime, bool]]:
    """Every entrant of the cup that has not withdrawn, in line order, with
    where it stands and whether it is held in."""
    rows = session.execute(
        select(EventEntrant, CupEntrantLine)
        .outerjoin(
            CupEntrantLine, col(CupEntrantLine.entrant_id) == col(EventEntrant.id)
        )
        .where(
            col(EventEntrant.event_id) == event_id,
            col(EventEntrant.withdrawn_at).is_(None),
        )
    ).all()
    line = [
        (row, line.joined_at if line else row.created_at, bool(line and line.held_in))
        for row, line in rows
    ]
    return sorted(line, key=lambda item: (item[1], ident(item[0])))
