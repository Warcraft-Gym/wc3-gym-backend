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


def season_points(won: int, played: int) -> float:
    """The points one season pays, before the participation bonus."""
    return won + (played - won) * 0.5


def rating(
    historical_rating: int | None,
    points_by_season: Mapping[int, float],
    system_seasons: Sequence[int],
) -> int:
    """The rating every season of the league decays and the seasons the player
    played pay."""
    baseline = historical_rating or 0
    # The stored historical rating is scaled, so divide it back to raw points
    value = baseline / 100.0 if baseline > 0 else 0.0

    for season_id in system_seasons:
        # Every season takes 15% off the points a player carries
        value *= 0.85
        points = points_by_season.get(season_id, 0.0)
        value += points
        if points > 0:
            value += 1.0

    # The scale creates separation between scores
    return int(value * 100.0)


def winrate(won: int, lost: int) -> float:
    """The share of the decided series or maps the player won, in percent."""
    total = won + lost
    return round(won / total * 100, 2) if total > 0 else 0.0


def per_season(series: int, seasons: int) -> float:
    """The series a player carries in an average season."""
    return round(series / seasons, 2) if seasons > 0 else 0.0
