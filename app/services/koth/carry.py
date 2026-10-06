"""Who holds the throne of each bracket of a night.

The crown is stored on the bracket, so the night before is read from a column
rather than walked back through its series, and so is the list of every closed
night's winners.
"""

from functools import cache
from typing import Any

from sqlalchemy import Integer, Select, and_, bindparam, func, select
from sqlalchemy.orm import Session as OrmSession
from sqlmodel import col

from app.core.db import Session
from app.models.base import ident
from app.models.enums import EventKind
from app.models.event_division import EventDivision
from app.models.event_entrant import EventEntrant
from app.models.event_history import HistoricalParticipant, KothHistoryEvent
from app.models.koth_night import KothBracketWinner, KothNightWinners
from app.models.season import Season
from app.models.user import User
from app.services.events import NEWEST_FIRST
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


@cache
def _winners_statements() -> tuple[Select[Any], Select[Any]]:
    """The page `limit`, `offset` of the published closed nights with their total,
    joined to their brackets and crowns as columns, and the count alone."""
    closed = (
        col(Season.kind) == EventKind.koth,
        col(Season.published).is_(True),
        col(Season.closed_at).is_not(None),
    )
    page = (
        select(col(Season.id), func.count().over().label("total"))
        .where(*closed)
        .order_by(*NEWEST_FIRST)
        .limit(bindparam("limit", type_=Integer))
        .offset(bindparam("offset", type_=Integer))
        .subquery()
    )
    statement = (
        select(
            page.c.total,
            col(Season.id),
            col(Season.starts_at),
            col(Season.start_date),
            col(KothHistoryEvent.date_label),
            col(EventDivision.id),
            col(EventDivision.name),
            col(EventDivision.lower_bound),
            func.coalesce(col(HistoricalParticipant.source_name), col(User.name)),
            col(EventEntrant.user_id),
            col(EventEntrant.race),
        )
        .join(page, page.c.id == Season.id)
        .outerjoin(KothHistoryEvent, col(KothHistoryEvent.event_id) == Season.id)
        .outerjoin(EventDivision, col(EventDivision.event_id) == Season.id)
        # The crown counts while its row stands in the bracket, not withdrawn, as on the board
        .outerjoin(
            EventEntrant,
            and_(
                col(EventEntrant.id) == EventDivision.king_entrant_id,
                col(EventEntrant.division_id) == EventDivision.id,
                col(EventEntrant.withdrawn_at).is_(None),
            ),
        )
        .outerjoin(
            HistoricalParticipant,
            col(HistoricalParticipant.id) == EventEntrant.historical_participant_id,
        )
        .outerjoin(User, col(User.id) == EventEntrant.user_id)
        .order_by(*NEWEST_FIRST, col(EventDivision.position))
    )
    return statement, select(func.count()).select_from(Season).where(*closed)


def winners(limit: int = 500, offset: int = 0) -> tuple[list[KothNightWinners], int]:
    """One page of the published closed nights, newest start first, each with
    the king every bracket ended with, and the count of every such night.

    The list calls a king a winner. One statement, and a second for the count
    only on a page past the end.
    """
    statement, count = _winners_statements()
    nights: dict[int, KothNightWinners] = {}
    total = 0
    with Session() as session:
        for (
            total,
            event_id,
            starts_at,
            start_date,
            label,
            division_id,
            name,
            lower_bound,
            king,
            user_id,
            race,
        ) in session.execute(statement, {"limit": limit, "offset": offset}):
            night = nights.get(event_id)
            if night is None:
                night = nights[event_id] = KothNightWinners(
                    event_id=event_id,
                    date=starts_at.date() if starts_at else start_date,
                    date_label=label,
                )
            if division_id is None:
                continue
            night.winners.append(
                KothBracketWinner(
                    bracket=name,
                    lower_bound=lower_bound,
                    name=king,
                    user_id=user_id,
                    race=race.value if race is not None else None,
                )
            )
        if not nights and offset:
            # A page past the end holds no row to carry the count
            total = session.scalar(count) or 0
    return list(nights.values()), total
