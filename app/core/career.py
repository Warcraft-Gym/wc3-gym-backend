"""The career rating rule and the career averages, as Python.

A season pays a player one point for every series he won and half a point for
every other series he played, and one more point to everyone who played it at
all. Every season of the league first takes 15% off the rating a player
carries, so a player who stops playing fades. The historical baseline enters
the fold as a rating of its own and decays with the rest.

The rating is a fold over the seasons in ascending order, so it depends on
the whole league and not only on the player.
"""

from collections.abc import Mapping, Sequence

# GNL Rating calculation constants
GNL_RATING_MATCH_WIN_VALUE = 1.0
GNL_RATING_MATCH_LOSS_VALUE = 0.5
GNL_RATING_SEASON_PLAYED_VALUE = 1.0
GNL_RATING_DECAY_RATE_PER_SEASON = (
    0.15  # Every season remove 15% of each players' points
)
GNL_RATING_FLAT_MULTIPLIER = 100.0  # Creates separation between scores


def season_points(won: int, played: int) -> float:
    """The points one season pays, before the participation bonus."""
    return (
        won * GNL_RATING_MATCH_WIN_VALUE + (played - won) * GNL_RATING_MATCH_LOSS_VALUE
    )


def rating(
    historical_rating: int | None,
    points_by_season: Mapping[int, float],
    system_seasons: Sequence[int],
) -> int:
    """The rating every season of the league decays and the seasons the player
    played pay."""
    baseline = historical_rating or 0
    # The stored historical rating is scaled, so divide it back to raw points
    value = baseline / GNL_RATING_FLAT_MULTIPLIER if baseline > 0 else 0.0

    for season_id in system_seasons:
        value *= 1.0 - GNL_RATING_DECAY_RATE_PER_SEASON
        points = points_by_season.get(season_id, 0.0)
        value += points
        if points > 0:
            value += GNL_RATING_SEASON_PLAYED_VALUE

    return int(value * GNL_RATING_FLAT_MULTIPLIER)


def winrate(won: int, lost: int) -> float:
    """The share of the decided series or maps the player won, in percent."""
    total = won + lost
    return round(won / total * 100, 2) if total > 0 else 0.0


def per_season(series: int, seasons: int) -> float:
    """The series a player carries in an average season."""
    return round(series / seasons, 2) if seasons > 0 else 0.0
