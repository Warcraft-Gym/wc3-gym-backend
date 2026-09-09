"""Which map each game is played on, when the rules say the loser picks.

A 2-1 fits two orders of maps, so the rule cannot answer game 2 until game 1
is won. These tests pin what the rule offers as each game is decided.
"""

from app.core.map_order import DEFAULT_RULES, maps_by_game, other_side

FIXED, A_PICK, B_PICK = 10, 21, 22
PICKS: dict[str, int | None] = {"A": A_PICK, "B": B_PICK}


def test_the_sides_are_two_and_each_is_the_other_s_other() -> None:
    assert other_side("A") == "B"
    assert other_side("B") == "A"


def test_game_one_takes_the_round_map_and_the_rest_wait_on_a_winner() -> None:
    assert maps_by_game(DEFAULT_RULES, FIXED, PICKS, {}) == {
        1: FIXED,
        2: None,
        3: None,
    }


def test_a_loser_game_takes_the_map_the_previous_loser_picked() -> None:
    """A won game 1, so B lost it and game 2 is B's pick."""
    assert maps_by_game(DEFAULT_RULES, FIXED, PICKS, {1: "A"}) == {
        1: FIXED,
        2: B_PICK,
        3: None,
    }
    # B then won game 2, so game 3 falls to A's pick
    assert maps_by_game(DEFAULT_RULES, FIXED, PICKS, {1: "A", 2: "B"}) == {
        1: FIXED,
        2: B_PICK,
        3: A_PICK,
    }


def test_the_two_orders_of_a_two_one_differ_on_game_two() -> None:
    """The whole reason a game needs a winner: the same score, two map orders."""
    a_then_b = maps_by_game(DEFAULT_RULES, FIXED, PICKS, {1: "A", 2: "B", 3: "A"})
    b_then_a = maps_by_game(DEFAULT_RULES, FIXED, PICKS, {1: "B", 2: "A", 3: "A"})
    assert a_then_b[2] == B_PICK and b_then_a[2] == A_PICK
    assert a_then_b != b_then_a


def test_a_season_with_no_rules_plays_the_gnl_best_of_three() -> None:
    assert maps_by_game(None, FIXED, PICKS, {1: "A"}) == maps_by_game(
        DEFAULT_RULES, FIXED, PICKS, {1: "A"}
    )


def test_a_rule_the_app_cannot_place_leaves_its_game_open() -> None:
    """Only fixed and loser name a map; a veto or host game is the reporter's to say."""
    assert maps_by_game("veto,veto,veto", FIXED, PICKS, {1: "A"}) == {
        1: None,
        2: None,
        3: None,
    }


def test_a_round_with_no_map_leaves_game_one_open() -> None:
    assert maps_by_game(DEFAULT_RULES, None, PICKS, {})[1] is None


def test_a_side_that_picked_nothing_offers_nothing() -> None:
    assert (
        maps_by_game(DEFAULT_RULES, FIXED, {"A": A_PICK, "B": None}, {1: "A"})[2]
        is None
    )


def test_a_best_of_five_reads_every_rule_it_lists() -> None:
    rules = "fixed,loser,loser,loser,loser"
    offered = maps_by_game(rules, FIXED, PICKS, {1: "A", 2: "B", 3: "A", 4: "B"})
    assert list(offered) == [1, 2, 3, 4, 5]
    assert offered[4] == B_PICK and offered[5] == A_PICK
