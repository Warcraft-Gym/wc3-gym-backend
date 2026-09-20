"""Who held the throne of each bracket of a night.

Nothing stores a crown: the king of a bracket is the winner of the last
scored series of its chain, so the night before is read rather than carried
in a column.
"""

from sqlalchemy.orm import Session as OrmSession

from app.models.base import ident
from app.models.season import Season
from app.models.series import Series
from app.services import stage_engine
from app.services.koth.night import divisions_of, series_of


def kings_of(session: OrmSession, night: Season) -> dict[int, int]:
    """The king of each bracket position of that night, by the player behind him.

    The throne is the last scored series of the chain, so a bracket nobody
    played to the end has no king.
    """
    positions = {
        ident(division): division.position
        for division in divisions_of(session, ident(night))
    }
    chains: dict[int | None, list[Series]] = {}
    for row in series_of(session, ident(night)):
        chains.setdefault(row.division_id, []).append(row)
    kings: dict[int, int] = {}
    for division_id, chain in chains.items():
        played = [row for row in chain if stage_engine.scored(row)]
        winner = stage_engine.winner_of(played[-1]) if played else None
        if winner is not None and division_id in positions:
            kings[positions[division_id]] = winner
    return kings
