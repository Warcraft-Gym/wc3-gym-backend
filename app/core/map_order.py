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


def default_rules(best_of: int) -> str:
    """The rules of a best-of whose stage names none: a fixed game, then loser picks."""
    return ",".join(["fixed", *["loser"] * (best_of - 1)])


def cup_rules(best_of: int) -> str:
    """The rules of a series that vetoes by its best-of: game 1 plays the map
    the veto leaves, every later game the pick of the side that lost before."""
    return ",".join(["decider", *["loser"] * (best_of - 1)])


def cup_order(best_of: int, pool: int) -> list[str]:
    """The veto of a series that plays by its best-of over a pool this size.

    The sides ban in turn, the front side first, until as many maps are left as
    the series has games; then they pick in turn, one map for every game after
    the first; the one map left is the decider game 1 plays.
    """
    bans = max(pool - best_of, 0)
    return [f"Ban_{SIDES[step % 2]}" for step in range(bans)] + [
        f"Pick_{SIDES[step % 2]}" for step in range(best_of - 1)
    ]


def decider_of(pool: list[int], taken: list[int], complete: bool) -> int | None:
    """The map game 1 plays once the veto is done: the one nobody banned or picked."""
    if not complete:
        return None
    left = [map_id for map_id in pool if map_id not in set(taken)]
    return left[0] if len(left) == 1 else None


def rules_of(map_rules: str | None) -> list[str]:
    """One rule per game, in game order."""
    return [rule for rule in (map_rules or DEFAULT_RULES).split(",") if rule]


def maps_by_game(
    map_rules: str | None,
    fixed_map_id: int | None,
    picks: dict[str, int | None],
    winners: dict[int, str],
    *,
    queue: dict[str, list[int]] | None = None,
    decider: int | None = None,
) -> dict[int, int | None]:
    """The map to offer for each game, by game number counting from 1.

    `picks` names the map each side took in the veto, and `winners` the side
    that won each game played so far. A game whose map cannot be worked out
    yet answers None. A series that vetoes by its best-of hands over `queue`,
    every pick of each side in veto order, so a side that loses twice plays its
    second pick, and `decider`, the map game 1 plays.
    """
    offered: dict[int, int | None] = {}
    used = dict.fromkeys(SIDES, 0)
    for game_no, rule in enumerate(rules_of(map_rules), start=1):
        if rule == "fixed":
            offered[game_no] = fixed_map_id
        elif rule == "decider":
            offered[game_no] = decider
        elif rule == "loser":
            winner = winners.get(game_no - 1)
            if not winner:
                offered[game_no] = None
            elif queue is None:
                offered[game_no] = picks.get(other_side(winner))
            else:
                loser = other_side(winner)
                own = queue.get(loser, [])
                offered[game_no] = own[used[loser]] if used[loser] < len(own) else None
                used[loser] += 1
        else:
            offered[game_no] = None
    return offered
