"""Which map each game of a series is played on.

A season's map_rules names one rule per game. A fixed game takes the round's
map. A loser game takes the map picked by the side that lost the game before,
so the order of the picked maps is not known until the games are won. Every
other rule leaves its game without a map, and the side reporting names it.

This answer is a suggestion. What a game was played on is what the report
stored; this only says what to offer when nothing is stored yet.
"""

DEFAULT_RULES = "fixed,loser,loser"
SIDES = ("A", "B")


def other_side(side: str) -> str:
    """The side that is not this one."""
    return SIDES[1] if side == SIDES[0] else SIDES[0]


def rules_of(map_rules: str | None) -> list[str]:
    """One rule per game, in game order."""
    return [rule for rule in (map_rules or DEFAULT_RULES).split(",") if rule]


def maps_by_game(
    map_rules: str | None,
    fixed_map_id: int | None,
    picks: dict[str, int | None],
    winners: dict[int, str],
) -> dict[int, int | None]:
    """The map to offer for each game, by game number counting from 1.

    `picks` names the map each side took in the veto, and `winners` the side
    that won each game played so far. A game whose map cannot be worked out
    yet answers None.
    """
    offered: dict[int, int | None] = {}
    for game_no, rule in enumerate(rules_of(map_rules), start=1):
        if rule == "fixed":
            offered[game_no] = fixed_map_id
        elif rule == "loser":
            winner = winners.get(game_no - 1)
            offered[game_no] = picks.get(other_side(winner)) if winner else None
        else:
            offered[game_no] = None
    return offered
