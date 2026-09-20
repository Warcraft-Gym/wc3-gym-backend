"""The one read the KOTH run page and the public dashboard both draw.

Everything the night shows is here: the header, the rows no bracket holds
yet, and per bracket the king, the hint of who defended last time, the series
on the table, the line that waits and the series already played. The read
costs a fixed number of statements, none of them per entrant or per series,
because the dashboard polls it while the night runs.
"""

from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session as OrmSession
from sqlmodel import col

from app.core.db import Session
from app.core.exceptions import NotFoundError
from app.models.base import ident
from app.models.enums import EventKind
from app.models.event_division import EventDivision
from app.models.event_entrant import EventEntrant
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
Line = tuple[str, str | None]
NOBODY: Line = ("", None)


def read(night_id: int | None = None, public: bool = False) -> KothBoard:
    """The whole night, or tonight's night when no id is named."""
    with Session() as session:
        night = _night(session, night_id)
        if public and not night.published:
            raise NotFoundError(f"KOTH night not found by id: {night_id}")
        event_id = ident(night)
        entrants = _entrants(session, event_id)
        series = series_of(session, event_id)
        mmrs = _mmrs(session, entrants)
        users = _users(session, entrants)
        replays = _replays(session, series)
        defenders = _defenders(session, night)
        chains: dict[int | None, list[Series]] = {}
        for row in series:
            chains.setdefault(row.division_id, []).append(row)
        busy = _busy(series)
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
                    users,
                    mmrs,
                    replays,
                    busy,
                    defenders.get(division.position),
                )
                for division in divisions_of(session, event_id)
            ],
        )


def _bracket(
    division: EventDivision,
    field: Sequence[EventEntrant],
    chain: Sequence[Series],
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
        defender=_defender(defender, live, users, mmrs) if king is None else None,
        open_series=_open(open_row, by_id, users, mmrs)
        if open_row is not None
        else None,
        queue=_seats(seated, users, mmrs, busy),
        left=[
            _player(row, users, mmrs) for row in field if row.withdrawn_at is not None
        ],
        played=_played(chain, by_id, users, mmrs, replays),
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
        name, country = users.get(row.user_id, NOBODY)
        seat = seats.get(row.user_id)
        if seat is None:
            seat = KothSeat(
                user_id=row.user_id,
                name=name,
                country=country,
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
    by_id: dict[int, EventEntrant],
    users: dict[int, Line],
    mmrs: dict[int, int | None],
    replays: set[int],
) -> list[KothPlayed]:
    """Every scored series of the bracket, newest first, with what it did to
    the crown. The label walks the results in play order, so a crown an admin
    passed or emptied by hand shows on the bracket, not on a played row."""
    rows: list[KothPlayed] = []
    king: int | None = None
    for row in chain:
        winner = stage_engine.entrant_of(row)
        loser = stage_engine.entrant_of(row, takes_loser=True)
        if not stage_engine.scored(row) or winner is None or loser is None:
            continue
        # The king is a player, so the walk follows him over all his race rows
        sides = (row.player1_id, row.player2_id)
        won = row.player1_id if stage_engine.won_slot(row) == 1 else row.player2_id
        throne = "none" if king is not None and king not in sides else "moved"
        if king == won:
            throne = "held"
        if throne != "none":
            king = won
        if winner not in by_id or loser not in by_id:
            continue
        rows.append(
            KothPlayed(
                series_id=ident(row),
                winner=_player(by_id[winner], users, mmrs),
                loser=_player(by_id[loser], users, mmrs),
                throne=throne,
                replay=ident(row) in replays,
            )
        )
    return list(reversed(rows))


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
    name, country = users.get(row.user_id or 0, NOBODY)
    return KothPlayer(
        entrant_id=ident(row),
        user_id=row.user_id,
        name=name,
        country=country,
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
    it, because the dashboard draws this read all night.
    """
    ratings = race_ratings(session, [(row.user_id, _race(row)) for row in rows])
    mmrs: dict[int, int | None] = {}
    for row in rows:
        race = _race(row)
        if row.user_id is not None and race is not None:
            mmrs[ident(row)] = ratings.get((row.user_id, race))
    return mmrs


def _users(session: OrmSession, rows: Sequence[EventEntrant]) -> dict[int, Line]:
    """The name and the country of each player behind those rows, in four columns."""
    ids = {row.user_id for row in rows if row.user_id is not None}
    if not ids:
        return {}
    return {
        user_id: (name or tag or "", country)
        for user_id, name, tag, country in session.execute(
            select(
                col(User.id), col(User.name), col(User.battleTag), col(User.country)
            ).where(col(User.id).in_(ids))
        )
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


def _night(session: OrmSession, night_id: int | None) -> Season:
    """The night the read names, or the one that takes signups."""
    if night_id is None:
        return tonight(session)
    night = session.get(Season, night_id)
    if night is None or night.kind is not EventKind.koth:
        raise NotFoundError(f"KOTH night not found by id: {night_id}")
    return night


def place(row: EventEntrant) -> tuple[int, int]:
    """Where a row stands in line: its seed, and its id behind an unseeded row."""
    return (row.seed if row.seed is not None else LAST, ident(row))


def _race(row: EventEntrant) -> str | None:
    """The race the row signed up on, as its value."""
    return row.race.value if row.race is not None else None
