"""Carry last night's king into tonight's chain.

Nothing stores a crown: the king of a bracket is the winner of the last
scored series of its chain, so the carry reads the night before and names
him first in the seed order. The rest of the bracket follows on MMR.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession
from sqlmodel import col

from app.core.db import Session
from app.models.base import ident
from app.models.enums import SeedSource
from app.models.event_entrant import EventEntrant, SeedWrite
from app.models.event_stage import EventStage
from app.models.season import Season
from app.models.series import Series
from app.services import stage_engine
from app.services.events import EventService
from app.services.koth.night import divisions_of, last_night, series_of


def follow_signup(event_id: int) -> None:
    """Seed the night after a signup, and draw each bracket once it holds two.

    A bracket draws on its own, so one player alone in another bracket never
    holds the night up. A bracket that already drew takes the late signup as
    one more challenger at the end of its chain. The seeds stay open while the
    night takes signups, because a locked stage refuses the seed write a later
    bracket needs; an admin who locks them by hand takes the night over.
    """
    with Session.begin() as session:
        night = session.get(Season, event_id)
        stage = session.scalars(
            select(EventStage)
            .where(col(EventStage.event_id) == event_id)
            .order_by(col(EventStage.position))
        ).first()
        if night is None or stage is None or stage.seeds_locked_at is not None:
            return
        stage_id = ident(stage)
        fields = _by_division(session, event_id)
        order = _kings_first(session, night, fields)
        chains: dict[int | None, list[Series]] = {}
        for row in series_of(session, event_id):
            chains.setdefault(row.division_id, []).append(row)
        ready = [
            division_id
            for division_id, field in fields.items()
            if len(field) >= 2 and division_id not in chains
        ]
        joining = [
            entrant_id
            for division_id, chain in chains.items()
            if division_id is not None
            for entrant_id in _stranded(chain, fields.get(division_id, []))
        ]
    EventService().set_seeds(
        event_id,
        stage_id,
        SeedWrite(
            source=SeedSource.manual if order else SeedSource.mmr, order=order or None
        ),
    )
    for division_id in ready:
        stage_engine.generate(event_id, stage_id, division_id)
    for entrant_id in joining:
        stage_engine.add_challenger(event_id, stage_id, entrant_id)


def kings_of(session: OrmSession, night: Season) -> dict[int, int]:
    """The king of each bracket position of that night, by the player behind him.

    The crown is stored on the bracket, so a bracket nobody played and a
    bracket whose king stepped down both answer nothing.
    """
    crowns = {
        division.king_entrant_id: division.position
        for division in divisions_of(session, ident(night))
        if division.king_entrant_id is not None
    }
    if not crowns:
        return {}
    wearers = session.scalars(
        select(EventEntrant).where(col(EventEntrant.id).in_(crowns))
    )
    return {
        crowns[ident(row)]: row.user_id for row in wearers if row.user_id is not None
    }


def _stranded(chain: list[Series], field: list[EventEntrant]) -> list[int]:
    """The entrants of a drawn bracket that no series of its chain names."""
    playing = {row.player1_id for row in chain} | {row.player2_id for row in chain}
    return [
        ident(row)
        for row in field
        if row.user_id is not None and row.user_id not in playing
    ]


def _by_division(session: OrmSession, event_id: int) -> dict[int, list[EventEntrant]]:
    """The entrants of each bracket that holds one, in signup order.

    A player who entered a bracket on two races holds two rows there and takes
    one seat, so the chain never pairs him with himself.
    """
    fields: dict[int, list[EventEntrant]] = {}
    rows = session.scalars(
        select(EventEntrant)
        .where(
            col(EventEntrant.event_id) == event_id,
            col(EventEntrant.withdrawn_at).is_(None),
        )
        .order_by(col(EventEntrant.id))
    )
    for row in rows:
        if row.division_id is not None:
            fields.setdefault(row.division_id, []).append(row)
    return {
        division_id: stage_engine._one_seat_per_player(field)
        for division_id, field in fields.items()
    }


def _kings_first(
    session: OrmSession, night: Season, fields: dict[int, list[EventEntrant]]
) -> list[int]:
    """The entrants the seed order names by hand: last night's kings, in order."""
    previous = last_night(session, before_id=ident(night))
    if previous is None:
        return []
    thrones = kings_of(session, previous)
    return [
        ident(row)
        for division in divisions_of(session, ident(night))
        for row in fields.get(ident(division), [])
        if row.user_id is not None and row.user_id == thrones.get(division.position)
    ]
