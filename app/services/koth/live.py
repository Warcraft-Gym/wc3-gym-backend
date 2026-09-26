"""Run a KOTH night live: the admin makes every series by hand.

Nothing is generated. An admin puts two race rows of one bracket on the
table, enters who won, and the bracket follows: the loser goes to the end of
the line and the crown moves under the rule the crown itself states. A
bracket holds one open series at a time, so the night never runs ahead of
what is actually being played.
"""

from itertools import pairwise

from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession
from sqlmodel import col

from app.core.db import Session
from app.core.exceptions import ApiError, BadRequestError, NotFoundError
from app.models.base import ident
from app.models.enums import EventKind, StageFormat
from app.models.event_division import EventDivision
from app.models.event_entrant import EventEntrant
from app.models.event_history import KothHistoryEvent
from app.models.event_stage import EventStage
from app.models.koth_night import (
    BoundsWrite,
    CrownWrite,
    KothBoard,
    QueueWrite,
    SeriesResult,
    SeriesStart,
)
from app.models.relationships import DBEventRound
from app.models.season import Season
from app.models.series import Series
from app.models.types import utcnow
from app.services import stage_engine
from app.services.koth import board
from app.services.koth.night import divisions_of, series_of
from app.services.koth.signup import recut

# The one round every series of a night is played in
ROUND_NAME = "King of the Hill"


def start_series(night_id: int, data: SeriesStart) -> KothBoard:
    """Put two race rows of one bracket on the table as a best of one."""
    with Session.begin() as session:
        night = _open_night(session, night_id)
        event_id = ident(night)
        first = _entrant(session, event_id, data.entrant1_id)
        second = _entrant(session, event_id, data.entrant2_id)
        if first.user_id is not None and first.user_id == second.user_id:
            raise BadRequestError("A player cannot play himself")
        if first.division_id is None or first.division_id != second.division_id:
            raise BadRequestError("Both rows play in the same bracket")
        if first.withdrawn_at is not None or second.withdrawn_at is not None:
            raise BadRequestError("A row that left tonight plays no series")
        chain = [
            row
            for row in series_of(session, event_id)
            if row.division_id == first.division_id
        ]
        if any(not stage_engine.scored(row) for row in chain):
            raise ApiError(
                409, {"error": "This bracket already has a series on the table"}
            )
        session.add(
            Series(
                round_id=ident(_round(session, _stage(session, event_id))),
                division_id=first.division_id,
                entrant1_id=ident(first),
                entrant2_id=ident(second),
                player1_id=first.user_id,
                player2_id=second.user_id,
                host_player_id=first.user_id or 0,
                sequence=max((row.sequence or 0) for row in chain) + 1 if chain else 1,
            )
        )
    return board.read(night_id)


def cancel_series(night_id: int, series_id: int) -> KothBoard:
    """Take an unplayed series off the table; a result is changed, never deleted."""
    with Session.begin() as session:
        _open_night(session, night_id)
        row = _series(session, night_id, series_id)
        if stage_engine.scored(row):
            raise BadRequestError("This series carries a result")
        session.delete(row)
    return board.read(night_id)


def set_result(night_id: int, series_id: int, data: SeriesResult) -> KothBoard:
    """Enter who won the one map, or turn a result of tonight around.

    The map score is the 1-0 every other reader of a series expects, so the
    player history, the head to head, the awards and the cards keep working.
    """
    with Session.begin() as session:
        _open_night(session, night_id)
        row = _series(session, night_id, series_id)
        was_scored = stage_engine.scored(row)
        was_slot = stage_engine.won_slot(row)
        row.player1_score = 1 if data.winner == 1 else 0
        row.player2_score = 0 if data.winner == 1 else 1
        stage_engine.game_one(session, row)
        session.flush()
        # The same result sent again moves neither the crown nor the line
        if not was_scored or was_slot != data.winner:
            stage_engine.after_score(session, row, was_scored, was_slot)
            beaten = stage_engine.entrant_of(row, takes_loser=True)
            loser = session.get(EventEntrant, beaten) if beaten else None
            if loser is not None:
                _to_the_end(session, loser)
    return board.read(night_id)


def set_queue(night_id: int, division_id: int, data: QueueWrite) -> KothBoard:
    """Order one bracket's line, first in line first; no other bracket moves."""
    with Session.begin() as session:
        night = _open_night(session, night_id)
        rows = {
            ident(row): row for row in _live_field(session, ident(night), division_id)
        }
        named = []
        for entrant_id in data.entrant_ids:
            row = rows.pop(entrant_id, None)
            if row is None:
                raise BadRequestError(f"Row {entrant_id} does not stand in line here")
            named.append(row)
        # A row the drag left out keeps its place behind the ones it names
        for place, row in enumerate(
            named + sorted(rows.values(), key=board.place), start=1
        ):
            row.seed = place
        session.flush()
    return board.read(night_id)


def set_crown(night_id: int, division_id: int, data: CrownWrite) -> KothBoard:
    """Pass the crown of one bracket on, or empty its throne.

    An empty throne is taken by the winner of the next series the bracket
    plays, and a king who left the throne is an ordinary row again.
    """
    with Session.begin() as session:
        night = _open_night(session, night_id)
        division = session.get(EventDivision, division_id)
        if division is None or division.event_id != ident(night):
            raise NotFoundError(f"Bracket not found by id: {division_id}")
        if data.entrant_id is None:
            division.king_entrant_id = None
        else:
            wearer = _entrant(session, ident(night), data.entrant_id)
            if wearer.division_id != division_id or wearer.withdrawn_at is not None:
                raise BadRequestError("The crown stays inside its own bracket")
            division.king_entrant_id = data.entrant_id
        session.flush()
    return board.read(night_id)


def set_bounds(night_id: int, data: BoundsWrite) -> KothBoard:
    """Move the MMR bounds of the brackets while the night runs.

    The bracket rows stay where they are, so their ids, their names, their
    order, the crowns and every series keep their place; only the bound moves.
    The night is then cut again by the new bounds, exactly as a signup cuts it.
    """
    with Session.begin() as session:
        night = _open_night(session, night_id)
        event_id = ident(night)
        if any(not stage_engine.scored(row) for row in series_of(session, event_id)):
            raise ApiError(409, {"error": "Finish or cancel the open series first."})
        brackets = divisions_of(session, event_id)
        named = {row.division_id: row.lower_bound for row in data.bounds}
        if len(named) != len(data.bounds) or named.keys() != {
            ident(row) for row in brackets
        }:
            raise BadRequestError("Name every bracket of the night exactly once")
        # The brackets read strongest first, so the bounds fall to 0 down the list
        wanted = [named[ident(row)] for row in brackets]
        if any(bound <= lower for bound, lower in pairwise(wanted)):
            raise BadRequestError("A stronger bracket opens at a higher MMR")
        if wanted[-1] != 0:
            raise BadRequestError("The weakest bracket opens at 0")
        for bracket in brackets:
            bracket.lower_bound = named[ident(bracket)]
        session.flush()
    recut(event_id)
    return board.read(night_id)


def remove_entrant(night_id: int, entrant_id: int) -> KothBoard:
    """Take a row out of tonight: it leaves the line, the throne and the table."""
    with Session.begin() as session:
        night = _open_night(session, night_id)
        row = _entrant(session, ident(night), entrant_id)
        row.withdrawn_at = utcnow()
        stage_engine.uncrown(session, [entrant_id])
        for series in series_of(session, ident(night)):
            if not stage_engine.scored(series) and entrant_id in (
                series.entrant1_id,
                series.entrant2_id,
            ):
                session.delete(series)
        session.flush()
    return board.read(night_id)


def restore_entrant(night_id: int, entrant_id: int) -> KothBoard:
    """Put a row that left back in; it stands at the end of the line."""
    with Session.begin() as session:
        night = _open_night(session, night_id)
        row = _entrant(session, ident(night), entrant_id)
        row.withdrawn_at = None
        _to_the_end(session, row)
    return board.read(night_id)


def _to_the_end(session: OrmSession, row: EventEntrant) -> None:
    """Send every race row of this player in his bracket to the end of the line.

    The whole bracket is numbered again in the order it already stands, so a
    row that never carried a seed keeps its place instead of jumping the line.
    """
    if row.division_id is None:
        return
    field = sorted(_live_field(session, row.event_id, row.division_id), key=board.place)
    moved = [other for other in field if other.user_id == row.user_id]
    waiting = [other for other in field if other.user_id != row.user_id]
    for place, other in enumerate(waiting + moved, start=1):
        other.seed = place
    session.flush()


def _live_field(
    session: OrmSession, event_id: int, division_id: int
) -> list[EventEntrant]:
    """Every row of one bracket that has not left tonight."""
    return list(
        session.scalars(
            select(EventEntrant).where(
                col(EventEntrant.event_id) == event_id,
                col(EventEntrant.division_id) == division_id,
                col(EventEntrant.withdrawn_at).is_(None),
            )
        )
    )


def _entrant(session: OrmSession, event_id: int, entrant_id: int) -> EventEntrant:
    """One row of this night."""
    row = session.get(EventEntrant, entrant_id)
    if row is None or row.event_id != event_id:
        raise NotFoundError(f"Entrant not found by id: {entrant_id}")
    return row


def _series(session: OrmSession, night_id: int, series_id: int) -> Series:
    """One series of this night."""
    row = session.get(Series, series_id)
    round_row = session.get(DBEventRound, row.round_id) if row else None
    if row is None or round_row is None or round_row.season_id != night_id:
        raise NotFoundError(f"Series not found by id: {series_id}")
    return row


def _open_night(session: OrmSession, night_id: int) -> Season:
    """The night, while it is still running; a closed night takes no write."""
    night = session.get(Season, night_id)
    if night is None or night.kind is not EventKind.koth:
        raise NotFoundError(f"KOTH night not found by id: {night_id}")
    if (
        night.closed_at is not None
        or session.get(KothHistoryEvent, night_id) is not None
    ):
        raise BadRequestError("The night is closed")
    return night


def _stage(session: OrmSession, event_id: int) -> EventStage:
    """The koth stage of the night; a night opens with exactly one."""
    stage = session.scalars(
        select(EventStage).where(
            col(EventStage.event_id) == event_id,
            col(EventStage.format) == StageFormat.koth,
        )
    ).first()
    if stage is None:
        raise BadRequestError("This night has no king of the hill stage")
    return stage


def _round(session: OrmSession, stage: EventStage) -> DBEventRound:
    """The one round the night is played in, written the first time it is needed."""
    row = session.scalars(
        select(DBEventRound)
        .where(col(DBEventRound.stage_id) == ident(stage))
        .order_by(col(DBEventRound.number))
    ).first()
    if row is None:
        row = DBEventRound(
            stage_id=ident(stage),
            season_id=stage.event_id,
            number=1,
            name=ROUND_NAME,
        )
        session.add(row)
        session.flush()
    return row
