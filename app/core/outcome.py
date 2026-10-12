"""Who a scored series sends on, read off any row with two sides and a score.

GNL and KOTH keep their series in `series` and a cup keeps its own in
`cup_series`. Both rows carry the same side and score columns, so one set of
rules answers both and neither engine imports the other.
"""

from typing import Protocol


class Sided(Protocol):
    """A series row: two sides, each an entrant or a player, and a score."""

    @property
    def player1_id(self) -> int | None: ...

    @property
    def player2_id(self) -> int | None: ...

    @property
    def entrant1_id(self) -> int | None: ...

    @property
    def entrant2_id(self) -> int | None: ...

    @property
    def player1_score(self) -> int | None: ...

    @property
    def player2_score(self) -> int | None: ...


def scored(row: Sided) -> bool:
    """Whether the series carries a result."""
    return row.player1_score is not None or row.player2_score is not None


def won_slot(row: Sided, takes_loser: bool = False) -> int | None:
    """The side the series sends on, 1 or 2, or the side it sends down; a
    draw or a series with no result sends neither."""
    if row.player1_score is None or row.player2_score is None:
        return None
    if row.player1_score == row.player2_score:
        return None
    first = row.player1_score > row.player2_score
    return 2 if first == takes_loser else 1


def entrant_of(row: Sided, takes_loser: bool = False) -> int | None:
    """The entrant the series sends on, which is what a team side carries."""
    slot = won_slot(row, takes_loser)
    if slot is None:
        return None
    return row.entrant1_id if slot == 1 else row.entrant2_id


def side_user(row: Sided, takes_loser: bool = False) -> int | None:
    """The user of the winning side, or of the losing one; a team side has none."""
    slot = won_slot(row, takes_loser)
    if slot is None:
        return None
    return row.player1_id if slot == 1 else row.player2_id


def winner_of(row: Sided) -> int | None:
    """The user the series sends on: nobody while it is unscored or drawn."""
    return side_user(row)


def stands_on_side(row: Sided, side: int) -> int | None:
    """Who stands on one side: its entrant, else the player the row names."""
    if side == 1:
        return row.entrant1_id or row.player1_id
    return row.entrant2_id or row.player2_id
