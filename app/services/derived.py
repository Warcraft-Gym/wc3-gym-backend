"""Series points, match scores and team standings, computed from the map
scores at read time.

Every number here comes from the map scores of the series and the score system
of the season that holds them, through app.core.scoring. The stored
player1_points, player2_points, team1_score, team2_score, final_score,
points_against and points_available columns are not read.

Two statements answer a whole response: one resolves the score system of every
match or season in it, and one sums the series on that system. points_case
reads the system and not the season, so seasons that share a system share a
statement, and there are two systems.

A team with no played series stands at zero, not at null.
"""

from collections.abc import Iterable

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.core.scoring import DEFAULT_SYSTEM, max_points, points, points_case
from app.models.match import Match, MatchPublic
from app.models.season import Season
from app.models.series import Series, SeriesPublic
from app.models.team import TeamPublic

type MatchScores = dict[int, tuple[int, int]]
# score system, series per week and number of weeks, per season
type SeasonRules = dict[int, tuple[str, int | None, int | None]]
# points for and points against, per (team, season)
type TeamSums = dict[tuple[int, int], list[int]]


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


def _rules_by_season(session: Session, season_ids: set[int]) -> SeasonRules:
    """The score system and the season length of every season, in one statement."""
    if not season_ids:
        return {}
    rows = session.execute(
        select(
            Season.id, Season.score_system, Season.series_per_week, Season.number_weeks
        ).where(Season.id.in_(season_ids))
    ).all()
    return {
        season_id: (system or DEFAULT_SYSTEM, per_week, weeks)
        for season_id, system, per_week, weeks in rows
    }


def _sums_by_team(session: Session, rules: SeasonRules) -> TeamSums:
    """The points for and against of every team of every season.

    One statement per score system, grouped by the two teams of a match, so a
    team collects both the matches it holds as team1 and as team2.
    """
    by_system: dict[str, list[int]] = {}
    for season_id, (system, _, _) in rules.items():
        by_system.setdefault(system, []).append(season_id)

    sums: TeamSums = {}
    for system, season_ids in by_system.items():
        rows = session.execute(
            select(
                Match.season_id,
                Match.team1_id,
                Match.team2_id,
                func.sum(
                    points_case(Series.player1_score, Series.player2_score, system)
                ),
                func.sum(
                    points_case(Series.player2_score, Series.player1_score, system)
                ),
            )
            .join(Series, Series.match_id == Match.id)
            .where(Match.season_id.in_(season_ids))
            .group_by(Match.season_id, Match.team1_id, Match.team2_id)
        ).all()
        for season_id, team1_id, team2_id, team1, team2 in rows:
            one, two = int(team1 or 0), int(team2 or 0)
            for team_id, own, opp in ((team1_id, one, two), (team2_id, two, one)):
                entry = sums.setdefault((team_id, season_id), [0, 0])
                entry[0] += own
                entry[1] += opp
    return sums


def fill_standings(session: Session, teams: Iterable[TeamPublic | None]) -> None:
    """Fill final_score, points_against and points_available on every
    seasons_info row of every team."""
    infos = [
        (team.id, info)
        for team in teams
        if team is not None
        for info in team.seasons_info
        if info.season_id is not None
    ]
    if not infos:
        return

    rules = _rules_by_season(session, {info.season_id for _, info in infos})
    sums = _sums_by_team(session, rules)

    for team_id, info in infos:
        system, per_week, weeks = rules.get(
            info.season_id, (DEFAULT_SYSTEM, None, None)
        )
        final, against = sums.get((team_id, info.season_id), [0, 0])
        info.final_score = final
        info.points_against = against
        info.points_available = (
            per_week * weeks * max_points(system) - final - against
            if per_week is not None and weeks is not None
            else None
        )
