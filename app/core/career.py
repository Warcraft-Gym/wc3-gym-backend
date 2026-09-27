"""The career rating rule and the career averages, as Python and as SQL.

A season pays a player one point for every series he won and half a point for
every other series he played, and one more point to everyone who played it at
all. Every season of the league first takes 15% off the rating a player
carries, so a player who stops playing fades. The historical baseline enters
the fold as a rating of its own and decays with the rest.

The fold over the seasons in ascending order sums to one term per season: a
season `age` seasons before the last pays its points times 0.85**age. Both
faces add those terms as integers in units of 1/SCALE and truncate the same
sum, so the database and Python answer the same rating in any order.
"""

from collections.abc import Mapping, Sequence
from fractions import Fraction

from sqlalchemy import BigInteger, SQLColumnExpression, case, literal

SCALE = 10**12
DECAY = Fraction(17, 20)  # every season keeps 85% of the rating


def season_points(won: int, played: int) -> float:
    """The points one season pays, before the participation bonus."""
    return won + (played - won) * 0.5


def decay_weight(age: int) -> int:
    """What 0.85**age is worth in units of 1/SCALE, rounded."""
    return round(DECAY**age * SCALE)


def season_weights(system_seasons: Sequence[int]) -> dict[int, int]:
    """The decay weight of every season of the league, the last one at 1."""
    last = len(system_seasons) - 1
    return {
        season_id: decay_weight(last - index)
        for index, season_id in enumerate(system_seasons)
    }


def rating(
    historical_rating: int | None,
    points_by_season: Mapping[int, float],
    system_seasons: Sequence[int],
) -> int:
    """The rating every season of the league decays and the seasons the player
    played pay."""
    baseline = historical_rating or 0
    # The stored historical rating is already scaled by 100
    total = baseline * decay_weight(len(system_seasons)) if baseline > 0 else 0
    for season_id, weight in season_weights(system_seasons).items():
        points = points_by_season.get(season_id, 0.0)
        if points > 0:
            # Points count in halves, so the scaled term is a whole number
            total += round((points + 1) * 100) * weight
    return total // SCALE


def season_score_sql(
    won: SQLColumnExpression[int],
    played: SQLColumnExpression[int],
    season_id: SQLColumnExpression[int],
    system_seasons: Sequence[int],
) -> SQLColumnExpression[int]:
    """The term of rating() one season pays, as SQL: 100*(points+1) times its weight."""
    weights = season_weights(system_seasons)
    if not weights:
        return literal(0)
    weight = case(weights, value=season_id, else_=0)
    return case((played > 0, (won + played + 2) * 50 * weight), else_=0)


def rating_sql(
    historical_rating: SQLColumnExpression[int | None],
    season_scores: SQLColumnExpression[int],
    system_seasons: Sequence[int],
) -> SQLColumnExpression[int]:
    """The rule of rating() as SQL, over the sum of season_score_sql()."""
    baseline = case(
        (
            historical_rating > 0,
            historical_rating * literal(decay_weight(len(system_seasons)), BigInteger),
        ),
        else_=0,
    )
    return (baseline + season_scores) // literal(SCALE, BigInteger)


def winrate_basis_points(won: int, lost: int) -> int:
    """The share of the decided series or maps the player won, in hundredths of
    a percent, with a half rounded up."""
    total = won + lost
    return (20000 * won + total) // (2 * total) if total > 0 else 0


def winrate(won: int, lost: int) -> float:
    """The share of the decided series or maps the player won, in percent."""
    return winrate_basis_points(won, lost) / 100


def winrate_sql(
    won: SQLColumnExpression[int], lost: SQLColumnExpression[int]
) -> SQLColumnExpression[int]:
    """The rule of winrate_basis_points() as SQL."""
    total = won + lost
    return case((total > 0, (20000 * won + total) // (2 * total)), else_=0)


def per_season(series: int, seasons: int) -> float:
    """The series a player carries in an average season."""
    return round(series / seasons, 2) if seasons > 0 else 0.0
