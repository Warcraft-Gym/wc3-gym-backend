"""Bracket maths for events: who plays whom, and who ranks where.

Entrants are passed in seed order, best seed first. None marks a bye.
"""

from collections.abc import Hashable, Sequence
from dataclasses import dataclass
from itertools import groupby
from typing import NamedTuple


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
    points: int
    game_diff: int


class Points(NamedTuple):
    """What a stage pays a table: per series won, per series drawn, per game won."""

    series_won: int = 0
    series_drawn: int = 0
    game_won: int = 1


# The scale that pays one point per game won, the table a stage reads by default
PER_GAME = Points()


type Result[T] = tuple[T, T, int, int]  # entrant a, entrant b, games a won, games b won


def standings[T: Hashable](
    entrants: Sequence[T], results: Sequence[Result[T]], pay: Points = PER_GAME
) -> list[Standing[T]]:
    """Rank by points, game difference, then head to head; seed order breaks the rest.

    `pay` is the stage's point scale; its default pays one point per game won.
    Head to head counts the games won in series between the tied entrants only.
    """
    won = dict.fromkeys(entrants, 0)
    lost = dict.fromkeys(entrants, 0)
    paid = dict.fromkeys(entrants, 0)
    for a, b, a_games, b_games in results:
        won[a] += a_games
        lost[a] += b_games
        won[b] += b_games
        lost[b] += a_games
        if a_games == b_games:
            paid[a] += pay.series_drawn
            paid[b] += pay.series_drawn
        else:
            paid[a if a_games > b_games else b] += pay.series_won

    def score(entrant: T) -> tuple[int, int]:
        points = paid[entrant] + won[entrant] * pay.game_won
        return points, won[entrant] - lost[entrant]

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


@dataclass(frozen=True)
class Slot:
    """One side of a planned series: a seed number, or the series it feeds from."""

    seed: int | None = None
    feeder: int | None = None
    takes_loser: bool = False


@dataclass(frozen=True)
class PlannedSeries:
    """One series of a plan: where it sits and where its two sides come from."""

    index: int
    round: int
    slot1: Slot
    slot2: Slot


@dataclass(frozen=True)
class Plan:
    """A whole bracket: the name of every round, and the series in play order.

    A series feeds from an earlier index of `series`, so writing the plan in
    order always knows the row a feeder points at.
    """

    rounds: list[str]
    series: list[PlannedSeries]


def _column_name(width: int) -> str:
    """The name of a full bracket column that holds `width` series."""
    return {1: "Final", 2: "Semifinals", 4: "Quarterfinals"}.get(
        width, f"Round of {2 * width}"
    )


def _power_of_two(field: int) -> int:
    size = 1
    while size < field:
        size *= 2
    return size


def elimination_plan(field: int, *, third_place: bool = False) -> Plan:
    """Every series of a single elimination bracket, in play order.

    The seeds over the power of two below the field play a play-in round and
    the rest enter the next column straight away, so the top seeds never meet
    an empty side. `third_place` adds the series the two beaten semi-finalists
    play, last in the final column.
    """
    column: list[Slot | None] = [
        Slot(seed=seed) if seed <= field else None
        for seed in bracket_order(_power_of_two(field))
    ]
    rounds: list[str] = []
    series: list[PlannedSeries] = []
    while len(column) > 1:
        pairs = list(zip(column[::2], column[1::2], strict=True))
        played = [pair for pair in pairs if None not in pair]
        if not played:
            column = [top or bottom for top, bottom in pairs]
            continue
        index = len(rounds)
        rounds.append(
            "Play-in" if len(played) < len(pairs) else _column_name(len(pairs))
        )
        carried: list[Slot | None] = []
        for top, bottom in pairs:
            if top is None or bottom is None:
                carried.append(top or bottom)
                continue
            carried.append(Slot(feeder=len(series)))
            series.append(PlannedSeries(len(series), index, top, bottom))
        column = carried
    if third_place and len(rounds) >= 2:
        semis = [row for row in series if row.round == len(rounds) - 2]
        if len(semis) == 2:
            series.append(
                PlannedSeries(
                    len(series),
                    len(rounds) - 1,
                    Slot(feeder=semis[0].index, takes_loser=True),
                    Slot(feeder=semis[1].index, takes_loser=True),
                )
            )
    return Plan(rounds, series)


def double_elimination_plan(field: int, *, grand_final: str = "one") -> Plan:
    """Every series of a double elimination bracket, upper then lower then final.

    The field is padded to a power of two, and a padded pair is a walkover the
    engine settles. `grand_final` is 'one', 'reset' for the second series the
    lower bracket winner earns, or 'skip' for no final series at all.
    """
    size = _power_of_two(field)
    seeds = [Slot(seed=seed) if seed <= field else None for seed in bracket_order(size)]
    rounds: list[str] = []
    series: list[PlannedSeries] = []

    def column(name: str, sides: list[tuple[Slot, Slot]]) -> list[Slot]:
        """Write one round and answer the winner slot of each series it holds."""
        index = len(rounds)
        rounds.append(name)
        made = []
        for slot1, slot2 in sides:
            made.append(Slot(feeder=len(series)))
            series.append(PlannedSeries(len(series), index, slot1, slot2))
        return made

    depth = size.bit_length() - 1
    # The upper bracket: an empty padded side becomes a walkover on generate
    upper = [
        column(
            "Upper bracket round 1",
            [
                (top or Slot(), bottom or Slot())
                for top, bottom in zip(seeds[::2], seeds[1::2], strict=True)
            ],
        )
    ]
    for step in range(2, depth + 1):
        name = "Upper bracket final" if step == depth else f"Upper bracket round {step}"
        upper.append(column(name, _pairs(upper[-1])))

    def losers(of: list[Slot]) -> list[Slot]:
        """The loser slot of every series a column holds."""
        return [Slot(feeder=slot.feeder, takes_loser=True) for slot in of]

    # The lower bracket: a minor round pairs its own winners, a major round
    # takes them against the losers the upper bracket has just sent down
    lower = column("Lower bracket round 1", _pairs(losers(upper[0])))
    number = 2
    for step in range(1, depth):
        name = (
            "Lower bracket final"
            if step == depth - 1
            else f"Lower bracket round {number}"
        )
        lower = column(name, list(zip(lower, losers(upper[step]), strict=True)))
        number += 1
        if step < depth - 1:
            lower = column(f"Lower bracket round {number}", _pairs(lower))
            number += 1

    if grand_final != "skip" and lower:
        final = column("Grand final", [(upper[-1][0], lower[0])])
        if grand_final == "reset":
            column(
                "Grand final reset",
                [(final[0], Slot(feeder=final[0].feeder, takes_loser=True))],
            )
    return Plan(rounds, series)


def _pairs(column: list[Slot]) -> list[tuple[Slot, Slot]]:
    """The adjacent pairs of a bracket column."""
    return list(zip(column[::2], column[1::2], strict=True))


def koth_chain(field: int) -> Plan:
    """The one round of a KOTH division: the king holds the throne in turn.

    Seeds 1 and 2 open, and the winner of each series meets the next seed.
    """
    series = [PlannedSeries(0, 0, Slot(seed=1), Slot(seed=2))]
    for seed in range(3, field + 1):
        series.append(
            PlannedSeries(len(series), 0, Slot(feeder=len(series) - 1), Slot(seed=seed))
        )
    return Plan(["Round 1"], series)


def round_robin_plan(field: int) -> Plan:
    """Every pairing of a round robin, one round per circle-method round."""
    rounds: list[str] = []
    series: list[PlannedSeries] = []
    for number, pairs in enumerate(round_robin(range(1, field + 1)), start=1):
        index = len(rounds)
        rounds.append(f"Round {number}")
        for top, bottom in pairs:
            if top is None or bottom is None:
                continue
            series.append(
                PlannedSeries(len(series), index, Slot(seed=top), Slot(seed=bottom))
            )
    return Plan(rounds, series)
