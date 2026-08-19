"""Series points, match scores, team standings, career totals and fantasy
scores, computed from the map scores at read time.

Every number here comes from the map scores of the series and the score system
of the season that holds them, through app.core.scoring and app.core.career.
Nothing stores player1_points, player2_points, team1_score, team2_score,
final_score, points_against or points_available.

Two statements answer a whole response: one resolves the score system of every
match or season in it, and one sums the series on that system. points_case
reads the system and not the season, so seasons that share a system share a
statement, and there are two systems.

A career answer costs two more statements: one groups the series of every
player by season, one names the seasons the league has played. Both are
constant, and a list of career rows also loads the players who have played
and hold no row of their own.

A fantasy answer costs two more statements on top of the standings pair: one
loads the series of every season in the answer, one loads the bets of its
captains. Every fantasy team scores against the season it names, so a mixed
answer pays each row by its own season. A bet result needs no statement at all,
because the map scores of the series already ride in the response.

A team with no played series stands at zero, not at null.
"""

from collections.abc import Iterable
from typing import NamedTuple

from sqlalchemy import case, func, or_, select, union_all
from sqlalchemy.orm import Session, aliased

from app.core import career, fantasy
from app.core.scoring import DEFAULT_SYSTEM, max_points, points, points_case
from app.models.fantasy_bet import FantasyBet, FantasyBetPublic
from app.models.fantasy_team import FantasyTeamPublic
from app.models.match import Match, MatchPublic
from app.models.player_career_stats import PlayerCareerStatsPublic
from app.models.season import Season
from app.models.series import Series, SeriesPublic
from app.models.team import TeamPublic
from app.models.user import User, UserReduced

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


class CareerTally(NamedTuple):
    """What one player took from one season: series he took part in, series
    won and lost, and maps won and lost. A drawn series is neither won nor
    lost."""

    played: int
    won: int
    lost: int
    games_won: int
    games_lost: int


class CareerPlayer(NamedTuple):
    """One player of the league, and his tally of every season he stood in."""

    name: str | None
    seasons: dict[int | None, CareerTally]


def _career_tallies(session: Session) -> dict[int, CareerPlayer]:
    """The season tally of every player who stands in a series, in one statement.

    A series counts for both of its players, so the two sides union before the
    grouping. A series with no map score still names the season the player
    stood in, and pays nothing.
    """
    player1, player2 = aliased(User), aliased(User)
    sides = union_all(
        select(
            Series.player1_id.label("user_id"),
            player1.name.label("player_name"),
            Match.season_id.label("season_id"),
            func.coalesce(Series.player1_score, 0).label("own"),
            func.coalesce(Series.player2_score, 0).label("opp"),
        )
        .join(Match, Match.id == Series.match_id, isouter=True)
        .join(player1, player1.id == Series.player1_id, isouter=True),
        select(
            Series.player2_id,
            player2.name,
            Match.season_id,
            func.coalesce(Series.player2_score, 0),
            func.coalesce(Series.player1_score, 0),
        )
        .join(Match, Match.id == Series.match_id, isouter=True)
        .join(player2, player2.id == Series.player2_id, isouter=True),
    ).subquery()

    own, opp = sides.c.own, sides.c.opp
    rows = session.execute(
        select(
            sides.c.user_id,
            sides.c.player_name,
            sides.c.season_id,
            func.sum(case((or_(own != 0, opp != 0), 1), else_=0)),
            func.sum(case((own > opp, 1), else_=0)),
            func.sum(case((opp > own, 1), else_=0)),
            func.sum(own),
            func.sum(opp),
        )
        .where(sides.c.user_id.is_not(None))
        .group_by(sides.c.user_id, sides.c.player_name, sides.c.season_id)
    ).all()

    players: dict[int, CareerPlayer] = {}
    for user_id, name, season_id, played, won, lost, games_won, games_lost in rows:
        player = players.setdefault(user_id, CareerPlayer(name, {}))
        player.seasons[season_id] = CareerTally(
            int(played or 0),
            int(won or 0),
            int(lost or 0),
            int(games_won or 0),
            int(games_lost or 0),
        )
    return players


def _system_seasons(session: Session) -> list[int]:
    """The seasons the league has played, in the order the decay applies."""
    season_ids = session.scalars(
        select(Match.season_id).join(Series, Series.match_id == Match.id).distinct()
    ).all()
    return sorted(season_id for season_id in season_ids if season_id is not None)


def _career_users(session: Session, user_ids: set[int]) -> dict[int, User]:
    """The players a career row must carry. The row reads their scalars only."""
    if not user_ids:
        return {}
    users = session.scalars(select(User).where(User.id.in_(user_ids))).all()
    return {user.id: user for user in users}


def _match_players(
    rows: list[PlayerCareerStatsPublic], tallies: dict[int, CareerPlayer]
) -> tuple[list[CareerPlayer | None], set[int]]:
    """The player every row stands for, and the players that hold no row.

    A row finds its player by user id. A historical row that holds no user id
    finds him by the name it carries, unless another row already stands for
    him.
    """
    claimed = {row.user_id for row in rows if row.user_id in tallies}
    by_name = {
        player.name: user_id
        for user_id, player in tallies.items()
        if player.name is not None
    }

    players: list[CareerPlayer | None] = []
    for row in rows:
        if row.user_id in tallies:
            players.append(tallies[row.user_id])
            continue
        user_id = by_name.get(row.player_name)
        if user_id is None or user_id in claimed:
            players.append(None)
            continue
        claimed.add(user_id)
        players.append(tallies[user_id])
    return players, set(tallies) - claimed


def _fill_row(
    row: PlayerCareerStatsPublic,
    player: CareerPlayer | None,
    system_seasons: list[int],
) -> None:
    """Fill the nine totals of one row from its historical baseline and its
    series."""
    seasons = player.seasons if player else {}
    series_won = (row.historical_series_won or 0) + sum(
        tally.won for tally in seasons.values()
    )
    series_lost = (row.historical_series_lost or 0) + sum(
        tally.lost for tally in seasons.values()
    )
    games_won = (row.historical_games_won or 0) + sum(
        tally.games_won for tally in seasons.values()
    )
    games_lost = (row.historical_games_lost or 0) + sum(
        tally.games_lost for tally in seasons.values()
    )
    seasons_played = (row.historical_seasons_played or 0) + sum(
        1 for season_id in seasons if season_id is not None
    )
    points = {
        season_id: career.season_points(tally.won, tally.played)
        for season_id, tally in seasons.items()
        if season_id is not None
    }

    row.rating = career.rating(row.historical_rating, points, system_seasons)
    row.series_won = series_won
    row.series_lost = series_lost
    row.games_won = games_won
    row.games_lost = games_lost
    row.seasons_played = seasons_played
    row.series_winrate = career.winrate(series_won, series_lost)
    row.games_winrate = career.winrate(games_won, games_lost)
    row.avg_series_per_season = career.per_season(
        series_won + series_lost, seasons_played
    )


def _fill_rows(
    session: Session, rows: list[PlayerCareerStatsPublic]
) -> tuple[dict[int, CareerPlayer], set[int], list[int]]:
    """Fill every row, and report the players that hold none."""
    tallies = _career_tallies(session)
    system_seasons = _system_seasons(session)
    players, unclaimed = _match_players(rows, tallies)
    for row, player in zip(rows, players, strict=True):
        _fill_row(row, player, system_seasons)
    return tallies, unclaimed, system_seasons


def fill_career(
    session: Session, stats: Iterable[PlayerCareerStatsPublic | None]
) -> None:
    """Fill the nine career totals of every row."""
    rows = [row for row in stats if row is not None]
    if rows:
        _fill_rows(session, rows)


def career_rows(
    session: Session, stored: list[PlayerCareerStatsPublic]
) -> list[PlayerCareerStatsPublic]:
    """Every career row of the league, by rating.

    A player who has played and holds no stored row stands in the list too,
    with a null id and no historical baseline, so a new player counts from his
    first result.
    """
    tallies, unclaimed, system_seasons = _fill_rows(session, stored)
    played = {
        user_id
        for user_id in unclaimed
        if any(tally.played for tally in tallies[user_id].seasons.values())
    }
    rows = list(stored)
    for user_id, user in _career_users(session, played).items():
        row = PlayerCareerStatsPublic(
            user_id=user_id,
            player_name=user.name,
            user=UserReduced.from_user_reduced(user),
            historical_rating=None,
            historical_series_won=None,
            historical_series_lost=None,
            historical_games_won=None,
            historical_games_lost=None,
            historical_seasons_played=None,
        )
        _fill_row(row, tallies[user_id], system_seasons)
        rows.append(row)

    # A row with no id sorts last of its rating, because no id orders it
    rows.sort(key=lambda stat: (-stat.rating, stat.id is None, stat.id or 0))
    return rows


def fantasy_series(
    session: Session, season_ids: set[int]
) -> dict[int, dict[int | None, list[fantasy.Series]]]:
    """The series of every named season, by season and by week, in one statement.

    The fantasy rules read the map scores and the two races, so the players join
    in as columns rather than load as objects.
    """
    if not season_ids:
        return {}

    player1, player2 = aliased(User), aliased(User)
    rows = session.execute(
        select(
            Match.season_id,
            Match.playday,
            Series.player1_id,
            player1.name,
            player1.race,
            Series.player2_id,
            player2.name,
            player2.race,
            Series.player1_score,
            Series.player2_score,
        )
        .join(Match, Match.id == Series.match_id)
        .join(player1, player1.id == Series.player1_id, isouter=True)
        .join(player2, player2.id == Series.player2_id, isouter=True)
        .where(Match.season_id.in_(season_ids))
    ).all()

    by_season: dict[int, dict[int | None, list[fantasy.Series]]] = {}
    for (
        season_id,
        week,
        one_id,
        one_name,
        one_race,
        two_id,
        two_name,
        two_race,
        one_score,
        two_score,
    ) in rows:
        weeks = by_season.setdefault(season_id, {})
        weeks.setdefault(week, []).append(
            fantasy.Series(
                week=week,
                player1=fantasy.Player(one_id, one_name, fantasy.race_value(one_race)),
                player2=fantasy.Player(two_id, two_name, fantasy.race_value(two_race)),
                player1_score=one_score,
                player2_score=two_score,
            )
        )
    return by_season


def _fantasy_bets(
    session: Session, captains: set[int], season_ids: set[int]
) -> dict[tuple[int, int], list[fantasy.Bet]]:
    """The bets of every named captain in every named season, in one statement.

    One statement covers the whole cross product, and a pair that holds no bet
    simply finds none.
    """
    if not captains or not season_ids:
        return {}

    winner, player1, player2 = aliased(User), aliased(User), aliased(User)
    rows = session.execute(
        select(
            FantasyBet.user_id,
            FantasyBet.season_id,
            FantasyBet.id,
            FantasyBet.bet_points,
            FantasyBet.winner_id,
            winner.name,
            Match.playday,
            Series.player1_id,
            player1.name,
            Series.player2_id,
            player2.name,
            Series.player1_score,
            Series.player2_score,
        )
        .join(Series, Series.id == FantasyBet.series_id)
        .join(Match, Match.id == Series.match_id, isouter=True)
        .join(winner, winner.id == FantasyBet.winner_id, isouter=True)
        .join(player1, player1.id == Series.player1_id, isouter=True)
        .join(player2, player2.id == Series.player2_id, isouter=True)
        .where(FantasyBet.user_id.in_(captains), FantasyBet.season_id.in_(season_ids))
    ).all()

    by_captain: dict[tuple[int, int], list[fantasy.Bet]] = {}
    for (
        user_id,
        season_id,
        bet_id,
        bet_points,
        winner_id,
        winner_name,
        week,
        one_id,
        one_name,
        two_id,
        two_name,
        one_score,
        two_score,
    ) in rows:
        by_captain.setdefault((user_id, season_id), []).append(
            fantasy.Bet(
                id=bet_id,
                points=bet_points,
                winner_id=winner_id,
                winner_name=winner_name,
                series=fantasy.Series(
                    week=week,
                    player1=fantasy.Player(one_id, one_name, None),
                    player2=fantasy.Player(two_id, two_name, None),
                    player1_score=one_score,
                    player2_score=two_score,
                ),
            )
        )
    return by_captain


def public_series(series: SeriesPublic | None) -> fantasy.Series | None:
    """One answered series, as the fantasy rules read it."""
    if series is None:
        return None
    return fantasy.Series(
        week=series.match.playday if series.match else None,
        player1=fantasy.Player(
            series.player1_id,
            series.player1.name if series.player1 else None,
            fantasy.race_value(series.player1.race) if series.player1 else None,
        ),
        player2=fantasy.Player(
            series.player2_id,
            series.player2.name if series.player2 else None,
            fantasy.race_value(series.player2.race) if series.player2 else None,
        ),
        player1_score=series.player1_score,
        player2_score=series.player2_score,
    )


def public_bet(bet: FantasyBetPublic) -> fantasy.Bet:
    """One answered bet, as the fantasy rules read it."""
    return fantasy.Bet(
        id=bet.id,
        points=bet.bet_points,
        winner_id=bet.winner_id,
        winner_name=bet.winner.name if bet.winner else None,
        series=public_series(bet.series),
    )


def _season_weeks(rules: SeasonRules, season_id: int | None) -> int | None:
    """How many weeks the season is played over."""
    return rules.get(season_id, (DEFAULT_SYSTEM, None, None))[2]


def _drafted_standing(
    rules: SeasonRules, sums: TeamSums, team_id: int | None, season_id: int | None
) -> fantasy.Standing | None:
    """What the drafted team stands at in the season of the fantasy team.

    The list answer carries no team name, and only the breakdown reads one.
    """
    if team_id is None or season_id is None:
        return None
    system, per_week, weeks = rules.get(season_id, (DEFAULT_SYSTEM, None, None))
    final, against = sums.get((team_id, season_id), [0, 0])
    available = (
        per_week * weeks * max_points(system) - final - against
        if per_week is not None and weeks is not None
        else 0
    )
    return fantasy.Standing(team_id, None, final, against, available)


def fill_fantasy_teams(
    session: Session, teams: Iterable[FantasyTeamPublic | None]
) -> None:
    """Fill the six score fields of every fantasy team, each against the season
    it names."""
    rows = [team for team in teams if team is not None]
    if not rows:
        return

    season_ids = {team.season_id for team in rows if team.season_id is not None}
    rules = _rules_by_season(session, season_ids)
    sums = _sums_by_team(session, rules)
    series = fantasy_series(session, season_ids)
    captains = {team.captain_id for team in rows if team.captain_id is not None}
    bets = _fantasy_bets(session, captains, season_ids)
    races = {
        season_id: fantasy.race_points(
            _season_weeks(rules, season_id), series.get(season_id, {})
        )
        for season_id in season_ids
    }

    for team in rows:
        season_id = team.season_id
        scores = fantasy.team_scores(
            drafted_players=[
                fantasy.Player(player.id, player.name, fantasy.race_value(player.race))
                for player in team.drafted_players
            ],
            drafted_race=fantasy.race_value(team.drafted_race),
            standing=_drafted_standing(rules, sums, team.drafted_team_id, season_id),
            bets=bets.get((team.captain_id, season_id), []),
            race_points=races.get(season_id, {}),
            series_by_week=series.get(season_id, {}),
            number_weeks=_season_weeks(rules, season_id),
        )
        team.player_points = scores["player_points"]
        team.bench_points = scores["bench_points"]
        team.team_points = scores["team_points"]
        team.race_points = scores["race_points"]
        team.bet_points = scores["bet_points"]
        team.total_points = scores["total_points"]


def fill_bet_results(bets: Iterable[FantasyBetPublic | None]) -> None:
    """Fill the result of every bet. This one costs no statement: the map scores
    of the series already ride in the answer."""
    for bet in bets:
        if bet is None:
            continue
        series = public_series(bet.series)
        bet.bet_result = (
            fantasy.bet_result(bet.bet_points, bet.winner_id, series)
            if series is not None
            else None
        )
