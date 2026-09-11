"""Bracket maths for events: who plays whom, and who ranks where.

Entrants are passed in seed order, best seed first. None marks a bye.
"""

from collections.abc import Hashable, Sequence
from dataclasses import dataclass
from itertools import groupby


def bracket_order(size: int) -> list[int]:
    """Seed numbers in bracket slot order, so seeds 1 and 2 can only meet in the final."""
    order = [1]
    while len(order) < size:
        mirror = 2 * len(order) + 1
        order = [seed for top in order for seed in (top, mirror - top)]
    return order


def single_elimination[T](seeds: Sequence[T]) -> list[tuple[T, T | None]]:
    """First-round pairs in bracket order: 1 vs N, padded to a power of two with byes."""
    size = 1
    while size < len(seeds):
        size *= 2
    slots = [seeds[s - 1] if s <= len(seeds) else None for s in bracket_order(size)]
    return [
        (top, bottom)
        for top, bottom in zip(slots[::2], slots[1::2], strict=True)
        if top is not None
    ]


def round_robin[T](entrants: Sequence[T]) -> list[list[tuple[T | None, T | None]]]:
    """Every pair once, one list per round, by the circle method; an odd field gets a bye."""
    ring: list[T | None] = list(entrants)
    if len(ring) % 2:
        ring.append(None)
    half = len(ring) // 2
    rounds = []
    for _ in range(len(ring) - 1):
        rounds.append([(ring[i], ring[-1 - i]) for i in range(half)])
        ring = [ring[0], ring[-1], *ring[1:-1]]
    return rounds


@dataclass(frozen=True)
class Standing[T]:
    entrant: T
    points: int  # games won
    game_diff: int


type Result[T] = tuple[T, T, int, int]  # entrant a, entrant b, games a won, games b won


def standings[T: Hashable](
    entrants: Sequence[T], results: Sequence[Result[T]]
) -> list[Standing[T]]:
    """Rank by points, game difference, then head to head; seed order breaks the rest.

    Head to head counts the games won in series between the tied entrants only.
    """
    won = dict.fromkeys(entrants, 0)
    lost = dict.fromkeys(entrants, 0)
    for a, b, a_games, b_games in results:
        won[a] += a_games
        lost[a] += b_games
        won[b] += b_games
        lost[b] += a_games

    def score(entrant: T) -> tuple[int, int]:
        return won[entrant], won[entrant] - lost[entrant]

    ranked: list[T] = []
    for _, tied in groupby(sorted(entrants, key=score, reverse=True), key=score):
        group = list(tied)
        h2h = dict.fromkeys(group, 0)
        for a, b, a_games, b_games in results:
            if a in h2h and b in h2h:
                h2h[a] += a_games
                h2h[b] += b_games
        ranked += sorted(group, key=h2h.__getitem__, reverse=True)
    return [Standing(e, *score(e)) for e in ranked]
