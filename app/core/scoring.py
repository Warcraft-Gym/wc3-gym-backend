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
