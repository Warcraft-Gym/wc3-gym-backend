"""Series points and match scores, computed from the map scores at read time.

Every number here comes from the map scores of the series and the score system
of the season that holds them, through app.core.scoring. The stored
player1_points, player2_points, team1_score and team2_score columns are not
read.

Two statements answer a whole response: one resolves the score system of every
match in it, and one sums the series of every match on that system. points_case
reads the system and not the season, so seasons that share a system share a
statement, and there are two systems.
"""

from collections.abc import Iterable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.scoring import DEFAULT_SYSTEM, points, points_case
from app.models.match import Match, MatchPublic
from app.models.season import Season
from app.models.series import Series, SeriesPublic

type MatchScores = dict[int, tuple[int, int]]


def _systems_by_match(session: Session, match_ids: set[int]) -> dict[int, str]:
    """The score system of the season of every match, in one statement."""
    if not match_ids:
        return {}
    rows = session.execute(
        select(Match.id, Season.score_system)
        .join(Season, Season.id == Match.season_id)
        .where(Match.id.in_(match_ids))
    ).all()
    return {match_id: system or DEFAULT_SYSTEM for match_id, system in rows}


def _scores_by_match(session: Session, systems: dict[int, str]) -> MatchScores:
    """The two team scores of every match, summed from its series."""
    by_system: dict[str, list[int]] = {}
    for match_id, system in systems.items():
        by_system.setdefault(system, []).append(match_id)

    scores: MatchScores = {}
    for system, match_ids in by_system.items():
        rows = session.execute(
            select(
                Series.match_id,
                func.sum(
                    points_case(Series.player1_score, Series.player2_score, system)
                ),
                func.sum(
                    points_case(Series.player2_score, Series.player1_score, system)
                ),
            )
            .where(Series.match_id.in_(match_ids))
            .group_by(Series.match_id)
        ).all()
        for match_id, team1, team2 in rows:
            scores[match_id] = (int(team1 or 0), int(team2 or 0))
    return scores


def _fill_match(match: MatchPublic, scores: MatchScores) -> None:
    """A match with no result yet stands at 0-0."""
    match.team1_score, match.team2_score = scores.get(match.id, (0, 0))


def fill_series(session: Session, series_list: Iterable[SeriesPublic | None]) -> None:
    """Fill the points of every series and the score of the match it carries."""
    rows = [series for series in series_list if series is not None]
    if not rows:
        return

    match_ids = {series.match_id for series in rows if series.match_id is not None}
    systems = _systems_by_match(session, match_ids)
    scores = _scores_by_match(session, systems)

    for series in rows:
        system = systems.get(series.match_id, DEFAULT_SYSTEM)
        series.player1_points = points(
            series.player1_score, series.player2_score, system
        )
        series.player2_points = points(
            series.player2_score, series.player1_score, system
        )
        if series.match:
            _fill_match(series.match, scores)


def fill_matches(session: Session, matches: Iterable[MatchPublic | None]) -> None:
    """Fill the two team scores of every match."""
    rows = [match for match in matches if match is not None]
    if not rows:
        return

    systems = _systems_by_match(session, {match.id for match in rows if match.id})
    scores = _scores_by_match(session, systems)
    for match in rows:
        _fill_match(match, scores)
