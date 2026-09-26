"""What an admin names to open and run a KOTH night, and what the board reads.

The night itself is an event row; the board is the one read the run page and
the public dashboard both draw, so nothing here is stored.
"""

from datetime import datetime
from typing import Annotated, Literal

from sqlmodel import SQLModel

from app.models.event_history import EventVideoPublic
from app.models.types import AwareUTC, NumToStr


class NightOpen(SQLModel):
    """Tonight's night: when it starts, what it is called, where it cuts.

    The bounds are the MMR each bracket opens at, weakest first, so the list
    reads the way the bracket numbers do. Left out, the night takes the bounds
    of the night before.
    """

    starts_at: Annotated[datetime, AwareUTC]
    name: Annotated[str | None, NumToStr] = None
    lower_bounds: list[int] | None = None


class SeriesStart(SQLModel):
    """The two race rows of one bracket an admin puts on the table."""

    entrant1_id: int
    entrant2_id: int


class SeriesResult(SQLModel):
    """The side of the series that won its one map."""

    winner: Literal[1, 2]


class QueueWrite(SQLModel):
    """The order one bracket stands in, by race row, first in line first."""

    entrant_ids: list[int]


class CrownWrite(SQLModel):
    """Who wears the crown of one bracket; no entrant empties the throne."""

    entrant_id: int | None = None


class BracketBound(SQLModel):
    """The MMR one bracket of the night opens at."""

    division_id: int
    lower_bound: int


class BoundsWrite(SQLModel):
    """Where the brackets of a running night cut, every bracket named once."""

    bounds: list[BracketBound]


class KothRow(SQLModel):
    """One race row a player holds in the bracket, with the rating behind it."""

    entrant_id: int
    race: str | None = None
    mmr: int | None = None


class KothSeat(SQLModel):
    """One player of the bracket: his place in line holds every race he signed
    up with there, and `busy` says he plays an open series of another bracket."""

    user_id: int
    name: str
    country: str | None = None
    rows: list[KothRow] = []
    busy: bool = False


class KothPlayer(SQLModel):
    """One player on one race row: a side of a series, or a row that left."""

    entrant_id: int
    user_id: int | None = None
    name: str
    country: str | None = None
    race: str | None = None
    mmr: int | None = None


class KothOpenSeries(SQLModel):
    """The series a bracket plays right now; a bracket holds one at a time."""

    series_id: int
    side1: KothPlayer
    side2: KothPlayer


class KothPlayed(SQLModel):
    """A series of tonight that carries a result.

    `throne` says what the result did to the crown: `moved` crowned the winner,
    `held` left it with the king who played, `none` was a side game.
    `winner_side` is the side of the series the winner played, so a client
    turns the result around with the other side and needs no series read.
    """

    series_id: int
    winner: KothPlayer
    loser: KothPlayer
    winner_side: Literal[1, 2]
    throne: Literal["moved", "held", "none"]
    replay: bool = False


class KothHistoricalSeries(SQLModel):
    series_id: int
    sequence: int
    side1: KothPlayer
    side2: KothPlayer
    winner_side: Literal[1, 2] | None = None
    result_unavailable: bool
    # From winner-stays-on order: shown on the board, left out of every record
    inferred_winner_side: Literal[1, 2] | None = None
    review_note: str | None = None


class KothBracket(SQLModel):
    """One bracket of the night as the run page and the dashboard draw it."""

    division_id: int
    name: str | None = None
    lower_bound: int | None = None
    historical: bool = False
    upper_bound: int | None = None
    historical_king: KothPlayer | None = None
    history: list[KothHistoricalSeries] = []
    king: KothSeat | None = None
    # The king of this bracket when the last closed night ended, a hint only
    defender: KothPlayer | None = None
    open_series: KothOpenSeries | None = None
    queue: list[KothSeat] = []
    left: list[KothPlayer] = []
    # Newest first
    played: list[KothPlayed] = []


class KothBoard(SQLModel):
    """The whole night in one read: its header, who waits for a bracket, and
    every bracket with its king, its line and the series it played."""

    historical: bool = False
    date_label: str | None = None
    videos: list[EventVideoPublic] = []
    night_id: int
    name: str
    starts_at: Annotated[datetime | None, AwareUTC] = None
    closed: bool = False
    entrant_count: int = 0
    series_count: int = 0
    # Rows no bracket holds yet; the admin places them, so they carry no rating
    unplaced: list[KothPlayer] = []
    brackets: list[KothBracket] = []
