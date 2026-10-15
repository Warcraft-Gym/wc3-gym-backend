"""Seeding, pairings and standings for event brackets."""

from itertools import combinations

import pytest

from app.core.brackets import (
    Plan,
    Slot,
    Standing,
    bracket_order,
    double_elimination_plan,
    round_robin,
    single_elimination,
    standings,
)


def test_eight_seeds_pair_1_v_8_and_split_the_top_two() -> None:
    assert bracket_order(8) == [1, 8, 4, 5, 2, 7, 3, 6]
    assert single_elimination(range(1, 9)) == [(1, 8), (4, 5), (2, 7), (3, 6)]


def test_five_entrants_give_the_top_three_seeds_three_byes() -> None:
    pairs = single_elimination(range(1, 6))
    assert pairs == [(1, None), (4, 5), (2, None), (3, None)]
    assert sum(bottom is None for _, bottom in pairs) == 3


def test_fourteen_entrants_give_seeds_one_and_two_the_byes() -> None:
    pairs = single_elimination(range(1, 15))
    assert len(pairs) == 8
    assert [top for top, bottom in pairs if bottom is None] == [1, 2]
    assert all(top + bottom == 17 for top, bottom in pairs if bottom is not None)
    placed = {s for pair in pairs for s in pair if s is not None}
    assert placed == set(range(1, 15))


def test_a_power_of_two_field_has_no_byes() -> None:
    pairs = single_elimination("abcdefghijklmnop")
    assert all(bottom is not None for _, bottom in pairs)


def test_odd_round_robin_meets_each_pair_once_and_each_sits_out_once() -> None:
    field = "abcde"
    rounds = round_robin(field)
    assert len(rounds) == 5
    played = [frozenset(p) for games in rounds for p in games if None not in p]
    assert len(played) == 10
    assert set(played) == set(map(frozenset, combinations(field, 2)))
    byes = [e for games in rounds for p in games if None in p for e in p if e]
    assert sorted(byes) == list(field)


def test_even_round_robin_has_no_byes_and_one_series_each_per_round() -> None:
    rounds = round_robin(range(6))
    assert len(rounds) == 5
    for games in rounds:
        assert len(games) == 3
        assert {e for pair in games for e in pair} == set(range(6))
    assert len({frozenset(pair) for games in rounds for pair in games}) == 15


def test_three_one_two_losses_outrank_one_two_nil_win() -> None:
    results = [("a", "c", 1, 2), ("a", "d", 1, 2), ("a", "e", 1, 2), ("b", "e", 2, 0)]
    table = standings("abcde", results)
    ranks = [row.entrant for row in table]
    assert ranks.index("a") < ranks.index("b")
    assert Standing("a", 3, -3) in table
    assert Standing("b", 2, 2) in table


def test_equal_points_rank_by_game_difference() -> None:
    results = [("a", "b", 2, 0), ("c", "d", 2, 1)]
    assert [row.entrant for row in standings("dcba", results)] == ["a", "c", "d", "b"]


def test_equal_points_and_difference_rank_by_head_to_head() -> None:
    """a and b tie on 3 points and 0 difference; a won their series."""
    results = [("a", "b", 2, 1), ("a", "c", 1, 2), ("b", "c", 2, 1), ("c", "d", 2, 0)]
    table = standings("bacd", results)
    assert [row.entrant for row in table] == ["c", "a", "b", "d"]
    assert Standing("a", 3, 0) in table
    assert Standing("b", 3, 0) in table


def test_a_full_tie_keeps_seed_order() -> None:
    assert [row.entrant for row in standings("xyz", [])] == ["x", "y", "z"]


def test_two_entrants_double_elimination_reach_a_grand_final() -> None:
    """Two entrants pad to four, so the loser drops to a lower bracket and
    every round holds a series."""
    plan = double_elimination_plan(2)
    assert "Grand final" in plan.rounds
    assert {row.round for row in plan.series} == set(range(len(plan.rounds)))


def drops(plan: Plan) -> dict[str, list[int]]:
    """Each lower round's dropped losers, in slot order, as their 1-based place
    within the upper round they lost in."""
    place = {}
    for number in range(len(plan.rounds)):
        held = [row.index for row in plan.series if row.round == number]
        place.update({index: spot for spot, index in enumerate(held, 1)})
    found: dict[str, list[int]] = {}
    for row in plan.series:
        name = plan.rounds[row.round]
        for slot in (row.slot1, row.slot2):
            feeder = None if slot.feeder is None else plan.series[slot.feeder]
            if (
                name.startswith("Lower bracket")
                and slot.takes_loser
                and feeder is not None
                and plan.rounds[feeder.round].startswith("Upper bracket")
            ):
                found.setdefault(name, []).append(place[feeder.index])
    return found


def test_losers_drop_into_the_lower_bracket_in_crossed_order() -> None:
    """Each drop round is reversed, and every second one also has its halves
    shifted, the alternating pattern of a standard double elimination."""
    assert drops(double_elimination_plan(8)) == {
        "Lower bracket round 1": [1, 2, 3, 4],
        "Lower bracket round 2": [2, 1],
        "Lower bracket final": [1],
    }
    assert drops(double_elimination_plan(16)) == {
        "Lower bracket round 1": list(range(1, 9)),
        "Lower bracket round 2": [4, 3, 2, 1],
        "Lower bracket round 4": [1, 2],
        "Lower bracket final": [1],
    }
    assert drops(double_elimination_plan(32)) == {
        "Lower bracket round 1": list(range(1, 17)),
        "Lower bracket round 2": [8, 7, 6, 5, 4, 3, 2, 1],
        "Lower bracket round 4": [2, 1, 4, 3],
        "Lower bracket round 6": [2, 1],
        "Lower bracket final": [1],
    }


@pytest.mark.parametrize("field", [8, 16, 32])
def test_no_upsets_meet_no_pair_twice_before_the_lower_final(field: int) -> None:
    """With the lower seed winning every series, the one repeat before the
    grand final is forced: seed 3 lost to seed 2 in the upper bracket and
    always meets the upper final loser, seed 2, in the lower final."""
    plan = double_elimination_plan(field)
    results: list[tuple[int, int]] = []
    met: set[frozenset[int]] = set()
    repeats = []

    def side(slot: Slot) -> int:
        """The seed that plays a side: its own, or a feeder's winner or loser."""
        if slot.seed is not None:
            return slot.seed
        assert slot.feeder is not None
        winner, loser = results[slot.feeder]
        return loser if slot.takes_loser else winner

    for row in plan.series:
        top, bottom = side(row.slot1), side(row.slot2)
        name = plan.rounds[row.round]
        pair = frozenset((top, bottom))
        if pair in met and not name.startswith("Grand final"):
            repeats.append((name, set(pair)))
        met.add(pair)
        results.append((min(top, bottom), max(top, bottom)))
    assert repeats == [("Lower bracket final", {2, 3})]
