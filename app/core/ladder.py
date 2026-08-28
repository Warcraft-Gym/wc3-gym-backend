"""The ladder scoring rule, as Python and as SQL.

A ladder match pays 3 points for a win and 1 for a loss. A match of
MIN_DURATION_S seconds or less pays nothing and is not a game, which is the
rule wc3.no scores the GNL ladder by. Both faces read the same rule, so a
value the database computes equals the value Python computes for the same
rows.
"""

from collections.abc import Iterable
from typing import NamedTuple, Protocol

from sqlalchemy import Case, ColumnElement, and_, case, literal

# A match this short or shorter is a drop, not a game
MIN_DURATION_S = 120
WIN_POINTS = 3
LOSS_POINTS = 1


class LadderRow(Protocol):
    """What the rule reads off a match, stored or straight from w3champions."""

    won: bool
    duration_s: int


class Totals(NamedTuple):
    """One player's record and points over a set of matches."""

    games: int
    wins: int
    losses: int
    points: int


def counted(duration_s: int) -> bool:
    """Whether a match of this length is a game at all."""
    return duration_s > MIN_DURATION_S


def points(won: bool, duration_s: int) -> int:
    """The ladder points one match pays the player."""
    if not counted(duration_s):
        return 0
    return WIN_POINTS if won else LOSS_POINTS


def totals(rows: Iterable[LadderRow]) -> Totals:
    """The record and the points of one player, over his matches."""
    games = wins = score = 0
    for row in rows:
        if not counted(row.duration_s):
            continue
        games += 1
        wins += int(bool(row.won))
        score += points(row.won, row.duration_s)
    return Totals(games=games, wins=wins, losses=games - wins, points=score)


def counted_clause(duration_s: ColumnElement[int]) -> ColumnElement[bool]:
    """The rule of counted() as SQL, over a duration column."""
    return duration_s > MIN_DURATION_S


def points_case(won: ColumnElement[bool], duration_s: ColumnElement[int]) -> Case[int]:
    """The rule of points() as SQL, over a result and a duration column."""
    return case(
        (and_(counted_clause(duration_s), won), literal(WIN_POINTS)),
        (counted_clause(duration_s), literal(LOSS_POINTS)),
        else_=literal(0),
    )
