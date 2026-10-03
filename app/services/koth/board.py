"""The one read the KOTH run page and the night page both draw.

Everything the night shows is here: the header, the rows no bracket holds
yet, and per bracket the king, the hint of who defended last time, the series
on the table, the line that waits and the series already played. The read
costs a fixed number of statements, none of them per entrant or per series,
because the stream view polls it while the night runs.
"""

from collections import Counter
from collections.abc import Collection, Iterator, Sequence
from typing import Literal, NamedTuple

from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession
from sqlmodel import col

from app.core.db import Session
from app.core.exceptions import NotFoundError
from app.models.base import ident
from app.models.enums import EventKind
from app.models.event_division import EventDivision
from app.models.event_entrant import EventEntrant
from app.models.event_history import KothHistoryEvent
from app.models.koth_crown_event import KothCrownEvent
from app.models.koth_night import (
    KothBoard,
    KothBracket,
    KothOpenSeries,
    KothPlayed,
    KothPlayer,
    KothRow,
    KothSeat,
)
from app.models.season import Season
from app.models.series import Series
from app.models.series_replay import DBSeriesReplay
from app.models.user import User
from app.services import stage_engine
from app.services.events import race_ratings
from app.services.koth import carry
from app.services.koth.night import divisions_of, series_of, tonight

# Where a row with no seed stands: behind every row that carries one
LAST = 1_000_000

# The name and the country of one player, which is all a player line shows
# The name, the country and the battle tag of one player
Line = tuple[str, str | None, str | None]
NOBODY: Line = ("", None, None)
# What one result did to the crown
Throne = Literal["moved", "held", "none"]


class Step(NamedTuple):
    """A crown change no result shows: the series it follows, the row it
    crowned and that row's player; no row is an empty throne."""

    after: int
    entrant_id: int | None
    user_id: int | None


def read(night_id: int | None = None, public: bool = False) -> KothBoard:
    """The whole night, or tonight's night when no id is named."""
    with Session() as session:
        return read_in(session, night_id, public)


def read_in(
    session: OrmSession, night_id: int | None = None, public: bool = False
) -> KothBoard:
    """The board as this session sees it, so a preview reads its own unsaved writes."""
    night, date_label = _night(session, night_id)
    if public and not night.published:
        raise NotFoundError(f"KOTH night not found by id: {night_id}")
    event_id = ident(night)
    if date_label is not None:
        from app.services.koth.history_board import read_archive

        return read_archive(session, night, date_label)
    entrants = _entrants(session, event_id)
    series = series_of(session, event_id)
    mmrs = _mmrs(session, entrants)
    users = _users(session, entrants)
    replays = _replays(session, series)
    defenders = _defenders(session, night)
    divisions = divisions_of(session, event_id)
    steps = crown_steps(session, [ident(row) for row in divisions]) if series else {}
    chains: dict[int | None, list[Series]] = {}
    for row in series:
        chains.setdefault(row.division_id, []).append(row)
    busy = _busy(series)
    # A series reads its sides among every row of the night, wherever they stand
    every_row = {ident(row): row for row in entrants}
    return KothBoard(
        night_id=event_id,
        name=night.name,
        starts_at=night.starts_at,
        closed=night.closed_at is not None,
        entrant_count=sum(1 for row in entrants if row.withdrawn_at is None),
        series_count=len(series),
        unplaced=[
            _player(row, users, {})
            for row in entrants
            if row.division_id is None and row.withdrawn_at is None
        ],
        brackets=[
            _bracket(
                division,
                [row for row in entrants if row.division_id == ident(division)],
                chains.get(ident(division), []),
                steps.get(ident(division), []),
                every_row,
                users,
                mmrs,
                replays,
                busy,
                defenders.get(division.position),
            )
            for division in divisions
        ],
    )


def _bracket(
    division: EventDivision,
    field: Sequence[EventEntrant],
    chain: Sequence[Series],
    steps: Sequence[Step],
    every_row: dict[int, EventEntrant],
    users: dict[int, Line],
    mmrs: dict[int, int | None],
    replays: set[int],
    busy: dict[int, int],
    defender: int | None,
) -> KothBracket:
    """One bracket: who wears the crown, who plays, who waits, what was played."""
    live = [row for row in field if row.withdrawn_at is None]
    by_id = {ident(row): row for row in field}
    open_row = next(
        (row for row in chain if not stage_engine.scored(row)),
        None,
    )
    king_id = division.king_entrant_id
    king = by_id.get(king_id) if king_id else None
    if king is not None and king.withdrawn_at is not None:
        king = None
    # A player on the table holds no seat in the line, whatever race row he plays
    playing = (
        {open_row.player1_id, open_row.player2_id} if open_row is not None else set()
    )
    seated = [
        row
        for row in live
        if row.user_id not in playing and (king is None or row.user_id != king.user_id)
    ]
    crowned = [row for row in live if king is not None and row.user_id == king.user_id]
    return KothBracket(
        division_id=ident(division),
        name=division.name,
        lower_bound=division.lower_bound,
        king=_seats(crowned, users, mmrs, busy)[0] if crowned else None,
        king_entrant_id=ident(king) if king is not None else None,
        defender=_defender(defender, live, users, mmrs) if king is None else None,
        open_series=_open(open_row, every_row, users, mmrs)
        if open_row is not None
        else None,
        queue=_seats(seated, users, mmrs, busy),
        left=[
            _player(row, users, mmrs) for row in field if row.withdrawn_at is not None
        ],
        played=_played(chain, steps, every_row, users, mmrs, replays),
    )


def _seats(
    rows: Sequence[EventEntrant],
    users: dict[int, Line],
    mmrs: dict[int, int | None],
    busy: dict[int, int],
) -> list[KothSeat]:
    """One seat per player, his race rows under it, in the order they stand."""
    seats: dict[int, KothSeat] = {}
    places: dict[int, tuple[int, int]] = {}
    for row in sorted(rows, key=place):
        if row.user_id is None:
            continue
        name, country, tag = users.get(row.user_id, NOBODY)
        seat = seats.get(row.user_id)
        if seat is None:
            seat = KothSeat(
                user_id=row.user_id,
                name=name,
                country=country,
                battle_tag=tag,
                rows=[],
                busy=busy.get(row.user_id) not in (None, row.division_id),
            )
            seats[row.user_id] = seat
            places[row.user_id] = place(row)
        seat.rows.append(
            KothRow(entrant_id=ident(row), race=_race(row), mmr=mmrs.get(ident(row)))
        )
    return sorted(seats.values(), key=lambda seat: places[seat.user_id])


def _played(
    chain: Sequence[Series],
    steps: Sequence[Step],
    by_id: dict[int, EventEntrant],
    users: dict[int, Line],
    mmrs: dict[int, int | None],
    replays: set[int],
) -> list[KothPlayed]:
    """Every scored series of the bracket, newest first, with what it did to
    the crown. The label walks the results and the crown events in play order,
    so it follows the crown the board shows."""
    rows: list[KothPlayed] = []
    for row, throne in walk(chain, steps):
        winner = stage_engine.entrant_of(row)
        loser = stage_engine.entrant_of(row, takes_loser=True)
        if winner is None or loser is None:
            continue
        if winner not in by_id or loser not in by_id:
            continue
        rows.append(
            KothPlayed(
                series_id=ident(row),
                winner=_player(by_id[winner], users, mmrs),
                loser=_player(by_id[loser], users, mmrs),
                winner_side=2 if stage_engine.won_slot(row) == 2 else 1,
                throne=throne,
                replay=ident(row) in replays,
                forfeit=row.result_kind == "forfeit",
            )
        )
    return list(reversed(rows))


def walk(
    chain: Sequence[Series], steps: Sequence[Step] = ()
) -> Iterator[tuple[Series, Throne]]:
    """Every scored series in play order with what it did to the crown: an empty
    throne or a beaten king moves it, a king who wins holds it, and a game
    between two others leaves it. A crown event between two series sets the
    king the next series meets."""
    for row, throne, _ in _reign(chain, steps):
        if row is not None:
            yield row, throne


def results_king(chain: Sequence[Series], steps: Sequence[Step] = ()) -> int | None:
    """The race row the walk crowns: the winner of the last series that moved or
    held the crown, the row of a crown event after it, or nobody."""
    king = None
    for _, throne, entrant_id in _reign(chain, steps):
        if throne != "none":
            king = entrant_id
    return king


def _reign(
    chain: Sequence[Series], steps: Sequence[Step]
) -> Iterator[tuple[Series | None, Throne, int | None]]:
    """The results and the crown events of a bracket in play order, each with
    what it did to the crown and the row it crowned. An event follows the
    series whose sequence it names, so it stays in place when that one goes."""
    king: int | None = None
    waiting = sorted(steps, key=lambda step: step.after)
    for row in chain:
        while waiting and waiting[0].after < (row.sequence or 0):
            step = waiting.pop(0)
            king = step.user_id
            yield None, "moved", step.entrant_id
        winner = stage_engine.entrant_of(row)
        loser = stage_engine.entrant_of(row, takes_loser=True)
        if not stage_engine.scored(row) or winner is None or loser is None:
            continue
        # The king is a player, so the walk follows him over all his race rows
        sides = (row.player1_id, row.player2_id)
        won = row.player1_id if stage_engine.won_slot(row) == 1 else row.player2_id
        throne: Throne = "none" if king is not None and king not in sides else "moved"
        if king == won:
            throne = "held"
        if throne != "none":
            king = won
        yield row, throne, winner
    for step in waiting:
        yield None, "moved", step.entrant_id


def crown_steps(
    session: OrmSession, division_ids: Collection[int]
) -> dict[int, list[Step]]:
    """The crown events of those brackets in one read, each in the order written."""
    if not division_ids:
        return {}
    steps: dict[int, list[Step]] = {}
    for division_id, after, entrant_id, user_id in session.execute(
        select(
            col(KothCrownEvent.division_id),
            col(KothCrownEvent.after_sequence),
            col(KothCrownEvent.entrant_id),
            col(EventEntrant.user_id),
        )
        .outerjoin(EventEntrant, col(EventEntrant.id) == KothCrownEvent.entrant_id)
        .where(col(KothCrownEvent.division_id).in_(division_ids))
        .order_by(col(KothCrownEvent.after_sequence), col(KothCrownEvent.id))
    ):
        steps.setdefault(division_id, []).append(Step(after, entrant_id, user_id))
    return steps


def _open(
    row: Series,
    by_id: dict[int, EventEntrant],
    users: dict[int, Line],
    mmrs: dict[int, int | None],
) -> KothOpenSeries | None:
    """The series on the table; a side whose row is gone leaves no open series."""
    first = by_id.get(row.entrant1_id or 0)
    second = by_id.get(row.entrant2_id or 0)
    if first is None or second is None:
        return None
    return KothOpenSeries(
        series_id=ident(row),
        side1=_player(first, users, mmrs),
        side2=_player(second, users, mmrs),
    )


def _defender(
    user_id: int | None,
    live: Sequence[EventEntrant],
    users: dict[int, Line],
    mmrs: dict[int, int | None],
) -> KothPlayer | None:
    """The king from the last event, shown while he holds a live row here."""
    row = next((row for row in live if row.user_id == user_id), None)
    return _player(row, users, mmrs) if row is not None else None


def _player(
    row: EventEntrant, users: dict[int, Line], mmrs: dict[int, int | None]
) -> KothPlayer:
    """One race row as a player line: no rating where none was read."""
    name, country, tag = users.get(row.user_id or 0, NOBODY)
    return KothPlayer(
        entrant_id=ident(row),
        user_id=row.user_id,
        name=name,
        country=country,
        battle_tag=tag,
        race=_race(row),
        mmr=mmrs.get(ident(row)),
    )


def _busy(series: Sequence[Series]) -> dict[int, int]:
    """Each player of an open series against the bracket he plays it in."""
    busy: dict[int, int] = {}
    for row in series:
        if stage_engine.scored(row) or row.division_id is None:
            continue
        for player_id in (row.player1_id, row.player2_id):
            if player_id is not None:
                busy[player_id] = row.division_id
    return busy


def _defenders(session: OrmSession, night: Season) -> dict[int, int]:
    """The king of each bracket position when the last closed night ended."""
    before = session.scalars(
        select(Season)
        .where(
            col(Season.kind) == EventKind.koth,
            ~col(Season.id).in_(select(col(KothHistoryEvent.event_id))),
            col(Season.id) < ident(night),
            col(Season.closed_at).is_not(None),
        )
        .order_by(col(Season.id).desc())
    ).first()
    return carry.kings_of(session, before) if before is not None else {}


def _replays(session: OrmSession, series: Sequence[Series]) -> set[int]:
    """The series of the night that hold at least one replay file."""
    ids = [ident(row) for row in series]
    if not ids:
        return set()
    return set(
        session.scalars(
            select(col(DBSeriesReplay.series_id)).where(
                col(DBSeriesReplay.series_id).in_(ids)
            )
        )
    )


def _mmrs(session: OrmSession, rows: Sequence[EventEntrant]) -> dict[int, int | None]:
    """Each row against the rating of the race it signed up on, in two reads.

    The board answers a figure per row and never the stored stat rows behind
    it, because the night page draws this read all night.
    """
    ratings = race_ratings(session, [(row.user_id, _race(row)) for row in rows])
    mmrs: dict[int, int | None] = {}
    for row in rows:
        race = _race(row)
        if row.user_id is not None and race is not None:
            mmrs[ident(row)] = ratings.get((row.user_id, race))
    return mmrs


def _users(session: OrmSession, rows: Sequence[EventEntrant]) -> dict[int, Line]:
    """The name and the country of each player behind those rows, in four columns,
    and the battle tag where two players of the night share a name: the stream
    polls the board, so it pays for a tag only where the tag reads them apart."""
    ids = {row.user_id for row in rows if row.user_id is not None}
    if not ids:
        return {}
    found = [
        (user_id, name or tag or "", country, tag)
        for user_id, name, tag, country in session.execute(
            select(
                col(User.id), col(User.name), col(User.battleTag), col(User.country)
            ).where(col(User.id).in_(ids))
        )
    ]
    shared = Counter(name.casefold() for _, name, _, _ in found)
    return {
        user_id: (name, country, tag if shared[name.casefold()] > 1 else None)
        for user_id, name, country, tag in found
    }


def _entrants(session: OrmSession, event_id: int) -> list[EventEntrant]:
    """Every row of the night, the ones that left among them."""
    return list(
        session.scalars(
            select(EventEntrant)
            .where(col(EventEntrant.event_id) == event_id)
            .order_by(col(EventEntrant.id))
        )
    )


def _night(session: OrmSession, night_id: int | None) -> tuple[Season, str | None]:
    """The named event and its archive label, without loading the source record."""
    if night_id is None:
        return tonight(session), None
    row = session.execute(
        select(Season, col(KothHistoryEvent.date_label))
        .outerjoin(KothHistoryEvent, col(KothHistoryEvent.event_id) == Season.id)
        .where(col(Season.id) == night_id, col(Season.kind) == EventKind.koth)
    ).first()
    if row is None:
        raise NotFoundError(f"KOTH night not found by id: {night_id}")
    return row[0], row[1]


def place(row: EventEntrant) -> tuple[int, int]:
    """Where a row stands in line: its seed, and its id behind an unseeded row."""
    return (row.seed if row.seed is not None else LAST, ident(row))


def _race(row: EventEntrant) -> str | None:
    """The race the row signed up on, as its value."""
    return row.race.value if row.race is not None else None
