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


type Result[T] = tuple[T, T | None, int, int]  # a, b or the bye, games a, games b


# The tie breaks a table may read, in the order a stage's ranking_rule names
# them: points, buchholz (the sum of the opponents' points), game_diff, and
# head_to_head, which runs last of all, inside the group the others leave tied
RANKING = ("points", "game_diff", "head_to_head")


def standings[T: Hashable](
    entrants: Sequence[T],
    results: Sequence[Result[T]],
    pay: Points = PER_GAME,
    rule: Sequence[str] = RANKING,
) -> list[Standing[T]]:
    """Rank by the tie breaks `rule` names, in order; seed order breaks the rest.

    `pay` is the stage's point scale; its default pays one point per game won.
    Head to head counts the games won in series between the tied entrants only,
    so it runs inside the group the other breaks leave tied, last of all, and a
    rule that leaves the word out leaves that group in the order it came in.
    A result whose second side is the bye pays the first side and counts its
    games, and adds nothing to either Buchholz sum because it has no opponent.
    """
    won = dict.fromkeys(entrants, 0)
    lost = dict.fromkeys(entrants, 0)
    paid = dict.fromkeys(entrants, 0)
    for a, b, a_games, b_games in results:
        for own, games, against in ((a, a_games, b_games), (b, b_games, a_games)):
            if own is None:
                continue
            won[own] += games
            lost[own] += against
            if games == against:
                paid[own] += pay.series_drawn
            elif games > against:
                paid[own] += pay.series_won

    points = {e: paid[e] + won[e] * pay.game_won for e in entrants}
    diff = {e: won[e] - lost[e] for e in entrants}
    buchholz = dict.fromkeys(entrants, 0)
    for a, b, _, _ in results:
        if b is None:
            continue
        buchholz[a] += points[b]
        buchholz[b] += points[a]
    measures = {"points": points, "game_diff": diff, "buchholz": buchholz}
    read = [measures[word] for word in rule if word in measures] or [points]

    def score(entrant: T) -> tuple[int, ...]:
        return tuple(measure[entrant] for measure in read)

    ranked = sorted(entrants, key=score, reverse=True)
    if "head_to_head" in rule:
        broken: list[T] = []
        for _, tied in groupby(ranked, key=score):
            group = list(tied)
            h2h = dict.fromkeys(group, 0)
            for a, b, a_games, b_games in results:
                if b is not None and a in h2h and b in h2h:
                    h2h[a] += a_games
                    h2h[b] += b_games
            broken += sorted(group, key=h2h.__getitem__, reverse=True)
        ranked = broken
    return [Standing(e, points[e], diff[e]) for e in ranked]


type Placing[T] = tuple[T, int]  # an entrant and the place he took in one lobby


def place_standings[T: Hashable](
    entrants: Sequence[T],
    placings: Sequence[Placing[T]],
    pay: Sequence[int],
) -> list[Standing[T]]:
    """Rank a free for all on the points its places pay, best place first.

    `pay` is what each place is worth, best place first, so "4,3,2,1" pays the
    winner of a lobby four. An entrant adds up every lobby he played and the
    best place he ever took breaks a tie on points; a place past the end of
    `pay` pays nothing.
    """
    points = dict.fromkeys(entrants, 0)
    # A place nobody took sits behind every place the scale pays
    best = dict.fromkeys(entrants, len(pay) + 1)
    for entrant, place in placings:
        if entrant not in points:
            continue
        points[entrant] += pay[place - 1] if 0 < place <= len(pay) else 0
        best[entrant] = min(best[entrant], place)
    ranked = sorted(entrants, key=lambda e: (points[e], -best[e]), reverse=True)
    return [Standing(e, points[e], 0) for e in ranked]


def swiss_pairs[T: Hashable](
    order: Sequence[T], met: Sequence[tuple[T | None, T | None]]
) -> list[tuple[T, T | None]] | None:
    """Pair one Swiss round from the table order, the leader first.

    Each entrant takes the best-placed opponent he has not met, so a pair sits
    inside its score group while one is free there. An odd field plays `None`,
    the bye, which falls to the lowest entrant that has not had one. It answers
    None when no pairing of the field is left.
    """
    seen = {frozenset(pair) for pair in met}
    field: list[T | None] = list(order)
    if len(field) % 2:
        field.append(None)
    return _paired(field, seen)


# The search backtracks over the whole field, which is flat out at Swiss sizes
def _paired[T: Hashable](
    field: Sequence[T | None], seen: set[frozenset[T | None]]
) -> list[tuple[T, T | None]] | None:
    """The first pairing of the field, top down, that repeats no pair."""
    if not field:
        return []
    top, rest = field[0], list(field[1:])
    if top is None:
        return None
    for index, other in enumerate(rest):
        if frozenset((top, other)) in seen:
            continue
        tail = _paired(rest[:index] + rest[index + 1 :], seen)
        if tail is not None:
            return [(top, other), *tail]
    return None


@dataclass(frozen=True)
class Slot:
    """One side of a planned series: a seed number, or the series it feeds from."""

    seed: int | None = None
    feeder: int | None = None
    takes_loser: bool = False


@dataclass(frozen=True)
class PlannedSeries:
    """One series of a plan: where it sits and where its sides come from.

    A lobby seats more than two, so `rest` holds every seat past the second
    and `slots` reads the whole lobby in seat order.
    """

    index: int
    round: int
    slot1: Slot
    slot2: Slot
    rest: tuple[Slot, ...] = ()

    @property
    def slots(self) -> tuple[Slot, ...]:
        return (self.slot1, self.slot2, *self.rest)


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


def round_robin_plan(field: int, per_entrant: int = 1) -> Plan:
    """Every pairing of a round robin, `per_entrant` circle rounds to a round.

    One circle round gives each entrant one series, so `per_entrant` of them
    make a round where each entrant plays that many different opponents. The
    last round is short when the circle rounds do not divide evenly, and an
    odd field drops the pair the bye sits in.
    """
    circle = round_robin(range(1, field + 1))
    step = max(per_entrant, 1)
    rounds: list[str] = []
    series: list[PlannedSeries] = []
    for number, start in enumerate(range(0, len(circle), step), start=1):
        index = len(rounds)
        rounds.append(f"Round {number}")
        for pairs in circle[start : start + step]:
            for top, bottom in pairs:
                if top is None or bottom is None:
                    continue
                series.append(
                    PlannedSeries(len(series), index, Slot(seed=top), Slot(seed=bottom))
                )
    return Plan(rounds, series)


def _lobbies(field: int, lobby_size: int) -> int:
    """How many lobbies a round of `field` holds; no lobby seats fewer than two."""
    return max(1, min(-(-field // lobby_size), field // 2))


def snake(count: int, lobbies: int) -> list[list[int]]:
    """Deal `count` seeds over `lobbies`, best seed first, turning at each end.

    Seed 1 opens the first lobby and seed `lobbies` the last, then the deal
    turns back, so every lobby takes one seed of each band.
    """
    dealt: list[list[int]] = [[] for _ in range(lobbies)]
    for seat in range(count):
        row, place = divmod(seat, lobbies)
        dealt[place if row % 2 == 0 else lobbies - 1 - place].append(seat + 1)
    return dealt


def ffa_bracket_plan(field: int, lobby_size: int, advance: int) -> Plan:
    """Rounds of free for all lobbies; the top `advance` places play on.

    Round 1 deals the seeds over its lobbies in snake order, one game each.
    Every later round holds the places that went through, over as many
    lobbies as they fill, and the last round is one lobby. A lobby past round
    1 opens with empty seats, which the round before it fills once every
    lobby of that round carries its places.
    """
    rounds: list[str] = []
    series: list[PlannedSeries] = []
    standing = field
    while True:
        lobbies = _lobbies(standing, lobby_size)
        index = len(rounds)
        rounds.append("Final" if lobbies == 1 else f"Round {index + 1}")
        for lobby in snake(standing, lobbies):
            slots = [Slot(seed=seed) if index == 0 else Slot() for seed in lobby]
            series.append(
                PlannedSeries(len(series), index, slots[0], slots[1], tuple(slots[2:]))
            )
        through = lobbies * advance
        # A round that sends its whole field on would draw itself again
        if lobbies == 1 or through >= standing:
            return Plan(rounds, series)
        standing = through


def ffa_league_plan(field: int, rounds: int = 1) -> Plan:
    """One free for all lobby that plays `rounds` series, the whole field in each.

    The lobby plays its series in one round, so the place points of every one
    of them add up into the same stage table.
    """
    slots = [Slot(seed=seed) for seed in range(1, field + 1)]
    return Plan(
        ["Round 1"],
        [
            PlannedSeries(number, 0, slots[0], slots[1], tuple(slots[2:]))
            for number in range(max(rounds, 1))
        ],
    )
