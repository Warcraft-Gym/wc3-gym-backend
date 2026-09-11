"""Seeding, pairings and standings for event brackets."""

from itertools import combinations

from app.core.brackets import (
    Standing,
    bracket_order,
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
