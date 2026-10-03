"""Run a KOTH night live: the admin makes every series by hand.

Nothing is generated. An admin puts two race rows of one bracket on the
table, enters who won, and the bracket follows: the loser goes to the end of
the line and the crown moves under the rule the crown itself states. A
bracket holds one open series at a time, so the night never runs ahead of
what is actually being played.
"""

from collections.abc import Callable, Sequence
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
    BracketMove,
    CrownWrite,
    KothBoard,
    QueueWrite,
    ResultAdd,
    SeriesResult,
    SeriesStart,
)
from app.models.relationships import DBEventRound
from app.models.season import Season
from app.models.series import Series
from app.models.series_side import SeriesSide
from app.models.types import utcnow
from app.models.user import User
from app.services import stage_engine
from app.services.events import _end_seed
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
            raise BadRequestError("Both players must stand in the same bracket")
        if first.withdrawn_at is not None or second.withdrawn_at is not None:
            raise BadRequestError("A player who left the event plays no series")
        every = series_of(session, event_id)
        chain = [row for row in every if row.division_id == first.division_id]
        if any(not stage_engine.scored(row) for row in chain):
            raise ApiError(
                409, {"error": "This bracket already has a series on the table"}
            )
        # A player plays one series at a time, in any bracket of the night
        busy = {
            player
            for row in every
            if not stage_engine.scored(row)
            for player in (row.player1_id, row.player2_id)
            if player is not None
        }
        playing = next(
            (row.user_id for row in (first, second) if row.user_id in busy), None
        )
        if playing is not None:
            user = session.get(User, playing)
            name = user.name if user else "This player"
            raise ApiError(409, {"error": f"{name} is playing in another bracket"})
        _add_series(session, event_id, first, second, chain)
    return board.read(night_id)


def _add_series(
    session: OrmSession,
    event_id: int,
    first: EventEntrant,
    second: EventEntrant,
    chain: Sequence[Series],
) -> Series:
    """Write one best of one between two rows of a bracket, after its chain."""
    row = Series(
        round_id=ident(_round(session, _stage(session, event_id))),
        division_id=first.division_id,
        entrant1_id=ident(first),
        entrant2_id=ident(second),
        player1_id=first.user_id,
        player2_id=second.user_id,
        host_player_id=first.user_id or 0,
        sequence=max((one.sequence or 0) for one in chain) + 1 if chain else 1,
    )
    session.add(row)
    session.flush()
    return row


def add_result(night_id: int, data: ResultAdd, preview: bool = False) -> KothBoard:
    """Record a series already played as the newest result of its bracket, with
    nobody moved in the line: the quick way to put a night's history back. A row
    that left may be a side, since it played before it left. The result lands
    before a series still on the table, which is played after it, and the crown
    follows the results unless it was passed by hand (_fix)."""

    def act(session: OrmSession, event_id: int) -> None:
        winner = _entrant(session, event_id, data.winner_id)
        loser = _entrant(session, event_id, data.loser_id)
        if winner.user_id is not None and winner.user_id == loser.user_id:
            raise BadRequestError("A player cannot play himself")
        if winner.division_id is None or winner.division_id != loser.division_id:
            raise BadRequestError("Both players must stand in the same bracket")
        chain = _chain(session, event_id, winner.division_id)
        played = [one for one in chain if stage_engine.scored(one)]
        row = _add_series(session, event_id, winner, loser, played)
        for waiting in chain:
            if not stage_engine.scored(waiting):
                waiting.sequence = (row.sequence or 0) + 1

        def score() -> None:
            row.player1_score, row.player2_score = 1, 0
            row.result_kind = "played"
            stage_engine.after_score(session, row, False, None)

        _fix(session, event_id, row, score)

    return _write(night_id, preview, act)


def clear_series(night_id: int) -> KothBoard:
    """Take every series off the night, played or on the table, and empty every
    throne, so a test run leaves no record. The signups and the line stay where
    they stand; a replay goes with its series."""

    def act(session: OrmSession, event_id: int) -> None:
        for row in series_of(session, event_id):
            session.delete(row)
        for division in divisions_of(session, event_id):
            division.king_entrant_id = None

    return _write(night_id, False, act)


def cancel_series(night_id: int, series_id: int, preview: bool = False) -> KothBoard:
    """Take a series off the table, or remove a played one from the night.

    A removed result erases its record and nothing else: no series is made or
    forfeited and the line stays. The crown follows the results left (_fix).
    """

    def act(session: OrmSession, event_id: int) -> None:
        row = _series(session, night_id, series_id)
        if stage_engine.scored(row):
            _fix(session, event_id, row, lambda: session.delete(row))
        else:
            session.delete(row)

    return _write(night_id, preview, act)


def set_result(
    night_id: int, series_id: int, data: SeriesResult, preview: bool = False
) -> KothBoard:
    """Enter who won the one map, or turn a result of tonight around.

    The map score is the 1-0 every other reader of a series expects, so the
    player history, the head to head, the awards and the cards keep working.
    A turned result reads played; the same winner sent again keeps its kind.
    """

    def act(session: OrmSession, event_id: int) -> None:
        row = _series(session, night_id, series_id)
        if stage_engine.scored(row):
            _fix(session, event_id, row, lambda: _score(session, row, data.winner))
        else:
            _score(session, row, data.winner)

    return _write(night_id, preview, act)


def _write(
    night_id: int, preview: bool, act: Callable[[OrmSession, int], None]
) -> KothBoard:
    """Run one write on an open night. A preview answers the board the write
    would give and rolls it back, so the run page shows what a fix changes."""
    if not preview:
        with Session.begin() as session:
            act(session, ident(_open_night(session, night_id)))
        return board.read(night_id)
    with Session() as session:
        act(session, ident(_open_night(session, night_id)))
        session.flush()
        answer = board.read_in(session, night_id)
        session.rollback()
    return answer


def _fix(
    session: OrmSession, event_id: int, row: Series, change: Callable[[], object]
) -> None:
    """Change or remove a played series and crown whoever the results then
    crown. A crown passed or emptied by hand since stays where the hand put it."""
    division = (
        session.get(EventDivision, row.division_id)
        if row.division_id is not None
        else None
    )
    if division is None:
        change()
        return
    worn = division.king_entrant_id
    by_hand = _player(session, worn) != _player(
        session, board.results_king(_chain(session, event_id, ident(division)))
    )
    change()
    session.flush()
    crowned = board.results_king(_chain(session, event_id, ident(division)))
    if by_hand or _player(session, crowned) == _player(session, worn):
        division.king_entrant_id = worn
        return
    heir = session.get(EventEntrant, crowned) if crowned is not None else None
    standing = (
        heir is not None
        and heir.withdrawn_at is None
        and heir.division_id == ident(division)
    )
    division.king_entrant_id = crowned if standing else None


def _chain(session: OrmSession, event_id: int, division_id: int) -> list[Series]:
    """The series of one bracket, in the order they were played."""
    return [
        row for row in series_of(session, event_id) if row.division_id == division_id
    ]


def _player(session: OrmSession, entrant_id: int | None) -> int | None:
    """The player behind a race row, the crown being a player's; a row with no
    account stands for itself."""
    row = session.get(EventEntrant, entrant_id) if entrant_id is not None else None
    if row is None:
        return None
    return row.user_id if row.user_id is not None else -ident(row)


def _score(session: OrmSession, row: Series, winner: int, kind: str = "played") -> None:
    """Write who won the one map and follow it into the crown and the line."""
    was_scored = stage_engine.scored(row)
    was_slot = stage_engine.won_slot(row)
    turned = not was_scored or was_slot != winner
    row.player1_score = 1 if winner == 1 else 0
    row.player2_score = 0 if winner == 1 else 1
    # The same result sent again keeps its kind, so a forfeit stays a forfeit
    if turned:
        row.result_kind = kind
    stage_engine.game_one(session, row)
    session.flush()
    # The same result sent again moves neither the crown nor the line
    if turned:
        stage_engine.after_score(session, row, was_scored, was_slot)
        beaten = stage_engine.entrant_of(row, takes_loser=True)
        loser = session.get(EventEntrant, beaten) if beaten else None
        if loser is not None:
            _to_the_end(session, loser)


def leave(session: OrmSession, event_id: int, rows: Sequence[EventEntrant]) -> None:
    """Withdraw race rows from a night, forfeiting what they owe first.

    A king who keeps another live row in his bracket passes the crown to it,
    with no forfeit; a series his crowned row plays on the table comes off with
    no result. Any other row in a series on the table loses it by forfeit. A
    king whose bracket has no series on the table and a player free to play in
    its line loses a forfeit series to the first of them, who takes the crown.
    Any other throne the rows wear is left empty.
    """
    ids = {ident(row) for row in rows}
    chain = series_of(session, event_id)
    divisions = divisions_of(session, event_id)
    kings = {ident(division): _king(session, division, ids) for division in divisions}
    heirs = {
        division_id: _heir(session, event_id, king, ids)
        for division_id, king in kings.items()
        if king is not None
    }
    for series in list(chain):
        sides = {series.entrant1_id, series.entrant2_id}
        if stage_engine.scored(series) or not ids & sides:
            continue
        king = kings.get(series.division_id or 0)
        heir = heirs.get(series.division_id or 0)
        if king is not None and heir is not None and ident(king) in sides:
            session.delete(series)
            chain.remove(series)
            continue
        _score(session, series, 2 if series.entrant1_id in ids else 1, "forfeit")
    for division in divisions:
        king = kings[ident(division)]
        # A forfeit above crowned the other side of the king's series
        if king is None or division.king_entrant_id != ident(king):
            continue
        heir = heirs[ident(division)]
        if heir is not None:
            division.king_entrant_id = ident(heir)
            continue
        bracket = [one for one in chain if one.division_id == division.id]
        if any(not stage_engine.scored(one) for one in bracket):
            continue
        challenger = _first_free(session, event_id, king, chain)
        if challenger is None:
            continue
        series = _add_series(session, event_id, king, challenger, bracket)
        _score(session, series, 2, "forfeit")
    left = utcnow()
    for row in rows:
        row.withdrawn_at = left
    stage_engine.uncrown(session, list(ids))
    session.flush()


def _king(
    session: OrmSession, division: EventDivision, ids: set[int]
) -> EventEntrant | None:
    """The crowned row of a bracket when it is one of the rows that leave."""
    king = (
        session.get(EventEntrant, division.king_entrant_id)
        if division.king_entrant_id in ids
        else None
    )
    # A pointer to a row of another bracket is an empty throne, not a king
    return king if king is not None and king.division_id == division.id else None


def _heir(
    session: OrmSession, event_id: int, king: EventEntrant, ids: set[int]
) -> EventEntrant | None:
    """The first other live row of a leaving king's player in his bracket."""
    return min(
        (
            row
            for row in _live_field(session, event_id, king.division_id or 0)
            if row.user_id == king.user_id and ident(row) not in ids
        ),
        key=board.place,
        default=None,
    )


def _first_free(
    session: OrmSession, event_id: int, king: EventEntrant, chain: Sequence[Series]
) -> EventEntrant | None:
    """The first row in the king's line whose player plays no series on the table."""
    if king.division_id is None:
        return None
    busy = {
        player
        for one in chain
        if not stage_engine.scored(one)
        for player in (one.player1_id, one.player2_id)
    }
    line = sorted(_live_field(session, event_id, king.division_id), key=board.place)
    return next(
        (
            row
            for row in line
            if row.user_id != king.user_id and row.user_id not in busy
        ),
        None,
    )


def set_queue(night_id: int, division_id: int, data: QueueWrite) -> KothBoard:
    """Order the named rows of one bracket's line, first in line first.

    The named rows swap among the places they already hold, so a row the write
    leaves out, such as the king or a player at the table, keeps its place.
    """
    with Session.begin() as session:
        night = _open_night(session, night_id)
        field = sorted(_live_field(session, ident(night), division_id), key=board.place)
        rows = {ident(row): row for row in field}
        named = []
        for entrant_id in data.entrant_ids:
            row = rows.pop(entrant_id, None)
            if row is None:
                raise BadRequestError(f"Row {entrant_id} does not stand in line here")
            named.append(row)
        order = iter(named)
        line = [row if ident(row) in rows else next(order) for row in field]
        for place, row in enumerate(line, start=1):
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
    The rows are then cut again by the rating stored when each was cut; both
    sides of a series on the table keep their bracket, also after it ends.
    """
    with Session.begin() as session:
        night = _open_night(session, night_id)
        event_id = ident(night)
        brackets = divisions_of(session, event_id)
        named = {row.division_id: row.lower_bound for row in data.bounds}
        if len(named) != len(data.bounds) or named.keys() != {
            ident(row) for row in brackets
        }:
            raise BadRequestError("Name every bracket of the event exactly once")
        # The brackets read strongest first, so the bounds fall to 0 down the list
        wanted = [named[ident(row)] for row in brackets]
        if any(bound <= lower for bound, lower in pairwise(wanted)):
            raise BadRequestError("A stronger bracket opens at a higher MMR")
        if wanted[-1] != 0:
            raise BadRequestError("The weakest bracket opens at 0")
        for bracket in brackets:
            bracket.lower_bound = named[ident(bracket)]
        session.flush()
    recut(event_id, bounds=True)
    return board.read(night_id)


def remove_entrant(night_id: int, entrant_id: int) -> KothBoard:
    """Take a row out of tonight; it forfeits what it owes, as a withdraw does."""
    with Session.begin() as session:
        night = _open_night(session, night_id)
        leave(session, ident(night), [_entrant(session, ident(night), entrant_id)])
    return board.read(night_id)


def restore_entrant(night_id: int, entrant_id: int) -> KothBoard:
    """Put a row that left back in; it takes the end seed of its bracket.

    The player's other rows keep their place, so a seat he still holds keeps
    its place in line, and a player with no other live row there joins the end.
    """
    with Session.begin() as session:
        night = _open_night(session, night_id)
        row = _entrant(session, ident(night), entrant_id)
        if row.withdrawn_at is None:
            user = session.get(User, row.user_id) if row.user_id else None
            raise BadRequestError(f"{user.name if user else 'This row'} has not left")
        row.withdrawn_at = None
        if row.division_id is not None:
            row.seed = _end_seed(session, row.event_id, row.division_id, entrant_id)
    return board.read(night_id)


def erase_entrant(night_id: int, entrant_id: int) -> KothBoard:
    """Delete a signup that no series names, live or left, so it leaves no record.

    A side of any series of the night, on the table, played or forfeit, stays
    on the record, and so does a row a seat of another series names. A crown
    the row wore leaves an empty throne; no other row moves.
    """
    with Session.begin() as session:
        night = _open_night(session, night_id)
        row = _entrant(session, ident(night), entrant_id)
        refusal = None
        if any(
            entrant_id in (one.entrant1_id, one.entrant2_id)
            for one in series_of(session, ident(night))
        ):
            refusal = "has a series in this event"
        elif (
            session.scalars(
                select(SeriesSide).where(col(SeriesSide.entrant_id) == entrant_id)
            ).first()
            is not None
        ):
            refusal = "holds a seat in another series"
        if refusal is not None:
            user = session.get(User, row.user_id) if row.user_id else None
            raise BadRequestError(
                f"{user.name if user else 'This row'} {refusal},"
                " so the signup stays on the record"
            )
        stage_engine.uncrown(session, [entrant_id])
        session.delete(row)
    return board.read(night_id)


def move_entrant(night_id: int, entrant_id: int, data: BracketMove) -> KothBoard:
    """Move one race row to another bracket by hand; it stands last there.

    The move is a placement by hand, so no cut moves the row back. A king who
    moves leaves his throne empty with no forfeit, and his other rows in that
    bracket go to the end of its line. His rows elsewhere stay where they are.
    """
    with Session.begin() as session:
        night = _open_night(session, night_id)
        event_id = ident(night)
        row = _entrant(session, event_id, entrant_id)
        target = session.get(EventDivision, data.division_id)
        if target is None or target.event_id != event_id:
            raise BadRequestError("That bracket is not part of this event")
        if row.withdrawn_at is not None:
            raise BadRequestError("Put the player back before moving him")
        if any(
            not stage_engine.scored(one)
            and entrant_id in (one.entrant1_id, one.entrant2_id)
            for one in series_of(session, event_id)
        ):
            raise ApiError(409, {"error": "Finish or cancel his series first"})
        old = row.division_id
        if old != data.division_id:
            throne = session.get(EventDivision, old) if old is not None else None
            was_king = throne is not None and throne.king_entrant_id == entrant_id
            row.division_id = data.division_id
            row.manual_placement = True
            row.seed = _end_seed(session, event_id, data.division_id, entrant_id)
            stage_engine.uncrown(session, [entrant_id])
            # A king's other rows in the old bracket join the end of its line
            if was_king and old is not None:
                rest = [
                    one
                    for one in _live_field(session, event_id, old)
                    if one.user_id == row.user_id
                ]
                if rest:
                    _to_the_end(session, rest[0])
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
        raise NotFoundError(f"KOTH event not found by id: {night_id}")
    if (
        night.closed_at is not None
        or session.get(KothHistoryEvent, night_id) is not None
    ):
        raise BadRequestError("The event is closed")
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
        raise BadRequestError("This event has no king of the hill stage")
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
