"""Who holds the throne of each bracket of a night.

The crown is stored on the bracket, so the night before is read from a column
rather than walked back through its series.
"""

from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession
from sqlmodel import col

from app.models.base import ident
from app.models.event_entrant import EventEntrant
from app.models.season import Season
from app.services.koth.night import divisions_of


def kings_of(session: OrmSession, night: Season) -> dict[int, int]:
    """The king of each bracket position of that night, by the player behind him.

    A bracket nobody played, a bracket whose king stepped down and a bracket
    whose wearer moved to another bracket all answer nothing.
    """
    crowns = {
        division.king_entrant_id: division
        for division in divisions_of(session, ident(night))
        if division.king_entrant_id is not None
    }
    if not crowns:
        return {}
    wearers = session.scalars(
        select(EventEntrant).where(col(EventEntrant.id).in_(crowns))
    )
    return {
        crowns[ident(row)].position: row.user_id
        for row in wearers
        if row.user_id is not None and row.division_id == ident(crowns[ident(row)])
    }
