"""The series scoring rule, as Python and as SQL.

A lost series keeps its map score (0 or 1). A won series converts to points from the
top of the scale, and the score system sets that top: standard 3, helpstone 4. Both
faces read the same rule, so a value the database computes equals the value Python
computes for the same scores.
"""

from sqlalchemy import Case, SQLColumnExpression, and_, case, literal

MAX_POINTS = {"standard": 3, "helpstone": 4}
DEFAULT_SYSTEM = "standard"


def max_points(system: str) -> int:
    """The points a series pays for a clean win under this score system."""
    return MAX_POINTS.get(system, MAX_POINTS[DEFAULT_SYSTEM])


def points(own: int | None, opp: int | None, system: str) -> int | None:
    """The points one side of a series takes from the two map scores."""
    if own is None and opp is None:
        return None
    if own is None or own < 0 or own > 2:
        raise ValueError("Score is not valid please check it.")
    if opp is None or opp < 0 or opp > 2:
        raise ValueError("Score is not valid please check it.")

    if own < 2:
        return own

    top = max_points(system)
    if opp == 0:
        return top
    if opp == 1:
        return top - 1
    return None


def points_case(
    own: SQLColumnExpression[int | None],
    opp: SQLColumnExpression[int | None],
    system: str,
) -> Case[int]:
    """The rule of points() as SQL, over two map score columns."""
    top = max_points(system)
    # SQL cannot raise: an own score below 2 reads back raw, and callers validate
    return case(
        (own < 2, own),
        (and_(own == 2, opp == 0), literal(top)),
        (and_(own == 2, opp == 1), literal(top - 1)),
    )
