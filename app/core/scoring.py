"""The series scoring rule, as Python and as SQL.

A lost series keeps its map score. A won series pays the top of the scale minus
the loser's maps, and the score system sets that top for a series that takes
`wins` maps: standard 2*wins-1, helpstone 2*wins (a Bo3 tops at 3 and 4). Both
faces read the same rule, so a value the database computes equals the value
Python computes for the same scores.
"""

from sqlalchemy import Case, SQLColumnExpression, and_, case, func

# What each system adds to 2*wins for the top of its scale
SYSTEMS = {"standard": -1, "helpstone": 0}
DEFAULT_SYSTEM = "standard"
DEFAULT_WINS = 2


def wins_needed(map_rules: str | None) -> int:
    """The maps a series takes to win: one per rule is one game, Bo3 when unset."""
    if not map_rules:
        return DEFAULT_WINS
    return len(map_rules.split(",")) // 2 + 1


def wins_needed_sql(
    map_rules: SQLColumnExpression[str | None],
) -> SQLColumnExpression[int]:
    """The rule of wins_needed() as SQL: the games are the commas plus one."""
    rules = func.nullif(map_rules, "")
    games = func.length(rules) - func.length(func.replace(rules, ",", "")) + 1
    return func.coalesce(games // 2 + 1, DEFAULT_WINS)


def fits(own: int, opp: int, wins: int) -> bool:
    """Whether two map scores fit a series that takes `wins` maps to win:
    neither above it, and not both at it. A read prices whatever is stored,
    and older seasons hold series that were never played."""
    return max(own, opp) <= wins and not own == opp == wins


def decided(own: int, opp: int, wins: int) -> bool:
    """Whether two map scores are a finished series: one side took the maps a
    win needs and the other took fewer. A Bo3 ends 2-0, 2-1, 1-2 or 0-2."""
    return max(own, opp) == wins and 0 <= min(own, opp) < wins


def recordable(own: int, opp: int, wins: int) -> bool:
    """Whether an admin may store these two map scores: a finished series, or
    0-0 for a series that was never played. A 0-0 pays both sides nothing and
    counts as a result, so the season it sits in can read complete."""
    return decided(own, opp, wins) or own == opp == 0


def max_points(system: str, wins: int = DEFAULT_WINS) -> int:
    """The points a series pays for a clean win under this score system."""
    return 2 * wins + SYSTEMS.get(system, SYSTEMS[DEFAULT_SYSTEM])


def points(
    own: int | None, opp: int | None, system: str, wins: int = DEFAULT_WINS
) -> int | None:
    """The points one side of a series takes from the two map scores."""
    if own is None and opp is None:
        return None
    if own is None or opp is None or not (0 <= own <= wins and 0 <= opp <= wins):
        raise ValueError("Score is not valid please check it.")
    if own < wins:
        return own
    if opp < wins:
        return max_points(system, wins) - opp
    return None  # no series ends wins-wins


def points_case(
    own: SQLColumnExpression[int | None],
    opp: SQLColumnExpression[int | None],
    system: str,
    wins: int = DEFAULT_WINS,
) -> Case[int]:
    """The rule of points() as SQL, over two map score columns."""
    # SQL cannot raise: an own score below wins reads back raw, and callers validate
    return case(
        (own < wins, own),
        (and_(own == wins, opp < wins), max_points(system, wins) - opp),
    )
