"""A cup's divisions and seeds: the cup-only rules beside the shared writes.

A cup chooses at creation whether it uses divisions (`cup_settings`). With
divisions off it plays one field, and every division write is refused. With
them on, the cut is made on the run page, and once the cup is drawn its
divisions stay as they are. A cup's entrants carry two pins of their own
(`cup_entrant_pin`), one for the division and one for the seed, so a new cut
keeps the seed pins and a reshuffle keeps the division pins.

The shared division and seed services ask here only for a `cup` event; every
other kind keeps `manual_placement` and today's rules.
"""

from collections.abc import Iterable

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session as OrmSession
from sqlmodel import col

from app.core.exceptions import ApiError, BadRequestError
from app.models.base import ident
from app.models.cup_series import CupSeries
from app.models.cup_settings import CupEntrantPin, CupSettings
from app.models.enums import EventKind
from app.models.event_division import EventDivision
from app.models.event_entrant import EventEntrant
from app.models.relationships import DBEventRound
from app.models.season import Season

NO_DIVISIONS = "This cup plays without divisions"
DRAWN = "The cup is drawn; undo the draw before its divisions change"


def is_cup(event: Season) -> bool:
    return event.kind is EventKind.cup


def uses_divisions(session: OrmSession, event: Season) -> bool | None:
    """Whether the cup splits into divisions; null for any other kind."""
    if not is_cup(event):
        return None
    row = session.get(CupSettings, ident(event))
    return row is not None and row.uses_divisions


def write_settings(
    session: OrmSession,
    event: Season,
    divisions: bool,
    points: str | None = None,
    custom_game: bool = False,
) -> None:
    """The settings row of a new cup: its divisions, the points table of a cup
    played over rounds, and whether it is a custom game on one map."""
    session.add(
        CupSettings(
            event_id=ident(event),
            uses_divisions=divisions,
            points_by_place=points,
            custom_game=custom_game,
        )
    )


def custom_game(session: OrmSession, event: Season) -> bool | None:
    """Whether the cup is a custom game on one map; null for any other kind."""
    if not is_cup(event):
        return None
    row = session.get(CupSettings, ident(event))
    return row is not None and row.custom_game


def points_text(session: OrmSession, event: Season) -> str | None:
    """The points table the cup stores, or null for the default."""
    row = session.get(CupSettings, ident(event))
    return row.points_by_place if row is not None else None


def _settings(session: OrmSession, event: Season) -> CupSettings:
    row = session.get(CupSettings, ident(event))
    if row is None:
        row = CupSettings(event_id=ident(event))
        session.add(row)
    return row


def set_custom_game(session: OrmSession, event: Season, on: bool) -> None:
    """Turn a cup's custom game on or off; the caller holds the game mode."""
    _settings(session, event).custom_game = on
    session.flush()


def set_points(session: OrmSession, event: Season, points: str | None) -> None:
    """Write the points table of a cup played over rounds; null keeps the default."""
    _settings(session, event).points_by_place = points
    session.flush()


def set_uses_divisions(session: OrmSession, event: Season, divisions: bool) -> None:
    """Switch a cup's divisions on or off. Off takes the divisions back, so it
    waits until the cup is not drawn."""
    row = _settings(session, event)
    if row.uses_divisions == divisions:
        return
    if not divisions:
        hold_undrawn(session, ident(event))
        clear_divisions(session, ident(event))
    row.uses_divisions = divisions
    session.flush()


def hold_divisions_on(session: OrmSession, event: Season) -> None:
    """Refuse a division write on a cup that plays without divisions."""
    if is_cup(event) and not uses_divisions(session, event):
        raise BadRequestError(NO_DIVISIONS)


def hold_undrawn(session: OrmSession, event_id: int, error: str = DRAWN) -> None:
    """Refuse a change once any stage of the cup holds its series."""
    drawn = session.scalar(
        select(col(CupSeries.id))
        .join(DBEventRound, col(DBEventRound.id) == col(CupSeries.round_id))
        .where(col(DBEventRound.season_id) == event_id)
        .limit(1)
    )
    if drawn is not None:
        raise ApiError(409, {"error": error})


def clear_divisions(session: OrmSession, event_id: int) -> None:
    """Take every division of the cup back, and the division pins with them."""
    session.execute(
        update(EventEntrant)
        .where(col(EventEntrant.event_id) == event_id)
        .values(division_id=None)
    )
    _unpin_divisions(session, event_id)
    session.execute(
        delete(EventDivision).where(col(EventDivision.event_id) == event_id)
    )


def _unpin_divisions(session: OrmSession, event_id: int) -> None:
    entrants = select(col(EventEntrant.id)).where(
        col(EventEntrant.event_id) == event_id
    )
    session.execute(
        update(CupEntrantPin)
        .where(col(CupEntrantPin.entrant_id).in_(entrants))
        .values(division_pinned=False)
    )


def reset_division_pins(session: OrmSession, event_id: int) -> None:
    """A new division list places nobody by hand yet; the seed pins stay."""
    _unpin_divisions(session, event_id)


def pins(session: OrmSession, entrant_ids: Iterable[int]) -> dict[int, CupEntrantPin]:
    """The pins of these entrants, in one read; an entrant with none is absent."""
    ids = list(entrant_ids)
    if not ids:
        return {}
    return {
        row.entrant_id: row
        for row in session.scalars(
            select(CupEntrantPin).where(col(CupEntrantPin.entrant_id).in_(ids))
        )
    }


def division_pinned(session: OrmSession, rows: Iterable[EventEntrant]) -> set[int]:
    """The entrants a runner placed in their division by hand."""
    return {
        entrant_id
        for entrant_id, pin in pins(session, [ident(row) for row in rows]).items()
        if pin.division_pinned
    }


def seed_pinned(session: OrmSession, rows: Iterable[EventEntrant]) -> set[int]:
    """The entrants whose seed a reshuffle keeps."""
    return {
        entrant_id
        for entrant_id, pin in pins(session, [ident(row) for row in rows]).items()
        if pin.seed_pinned
    }


def set_pins(
    session: OrmSession,
    entrant_id: int,
    division: bool | None = None,
    seed: bool | None = None,
) -> CupEntrantPin:
    """Write the pins the caller names; a pin left out stays."""
    row = session.get(CupEntrantPin, entrant_id)
    if row is None:
        row = CupEntrantPin(entrant_id=entrant_id)
        session.add(row)
    if division is not None:
        row.division_pinned = division
    if seed is not None:
        row.seed_pinned = seed
    session.flush()
    return row
