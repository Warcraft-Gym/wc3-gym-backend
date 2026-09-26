"""Series points, match scores, team standings, career totals and fantasy
scores, computed from the map scores at read time.

Every number here comes from the map scores of the series and the score system
of the season that holds them, through app.core.scoring and app.core.career.
Nothing stores player1_points, player2_points, team1_score, team2_score,
final_score, points_against or points_available.

Two statements answer a whole response: one resolves the scale of every
series, match or season in it, and one sums the series on that scale.
points_case reads the scale (score system and maps to win) and not the season,
so seasons that share a scale share a statement. A series reads its scale
through app.services.series_rules, which answers the rules of the same row in
the same statement. A series answer pays one more statement for the race every
player in it registered on for the season of its match.

A career answer costs two more statements: one groups the series of every
player by season, one names the seasons the league has played. Both are
constant, and a list of career rows also loads the players who have played
and hold no row of their own.

A fantasy answer costs two more statements on top of the standings pair: one
loads the series of every season in the answer, one loads the bets of its
captains. Every fantasy team scores against the season it names, so a mixed
answer pays each row by its own season. A bet result needs no statement at all,
because the map scores of the series already ride in the response.

A per-player season record costs two more statements: one groups the series
of the named players by season, one names the race of every opponent they met.
Neither grows with the number of players in the answer.

A team with no played series stands at zero, not at null.
"""

from collections.abc import Callable, Iterable
from typing import Any, Literal, NamedTuple

from sqlalchemy import (
    BigInteger,
    ColumnElement,
    Integer,
    SQLColumnExpression,
    String,
    and_,
    case,
    cast,
    func,
    null,
    or_,
    select,
    tuple_,
    union_all,
)
from sqlalchemy.orm import Mapped, Session, aliased
from sqlalchemy.sql.selectable import CTE, FromClause, Subquery
from sqlmodel import col

from app.core import career, fantasy
from app.core.ordering import SortOrder
from app.core.scoring import (
    DEFAULT_SYSTEM,
    DEFAULT_WINS,
    max_points,
    points,
    points_case,
    wins_needed,
    wins_needed_sql,
    wins_of,
)
from app.models.base import ident
from app.models.draft_series import DraftSeriesPublic
from app.models.enums import Race
from app.models.event_award import EventAward
from app.models.event_entrant import EventEntrant
from app.models.event_stage import EventStage
from app.models.fantasy_bet import FantasyBet, FantasyBetPublic
from app.models.fantasy_team import FantasyTeamPublic
from app.models.match import Match, MatchPublic
from app.models.player_career_stats import PlayerCareerStats, PlayerCareerStatsPublic
from app.models.relationships import DBEventRound, DBUserSeasonSignup
from app.models.season import (
    LEAGUE_SHORT_NAME,
    ROUND_COUNT,
    Season,
    progress_by_seasons,
)
from app.models.season_info import SeasonInfoPublic
from app.models.series import Series, SeriesPublic
from app.models.team import Team, TeamPublic
from app.models.user import (
    TrophyPublic,
    User,
    UserListPublic,
    UserPublic,
    UserReduced,
)
from app.services import series_rules

type MatchScores = dict[int, tuple[int, int]]
# score system and maps to win, the two arguments of the scoring rule
type Scale = tuple[str, int]
DEFAULT_SCALE: Scale = (DEFAULT_SYSTEM, DEFAULT_WINS)
# scale, series per week and number of weeks, per season
type SeasonRules = dict[int, tuple[Scale, int | None, int | None]]
# points for, points against, series won and series lost, per (team, season)
type TeamSums = dict[tuple[int, int], list[int]]


def _scale(system: str | None, map_rules: str | None) -> Scale:
    return system or DEFAULT_SYSTEM, wins_needed(map_rules)


def _scales_by_match(session: Session, match_ids: set[int]) -> dict[int, Scale]:
    """The scale of every match, in one statement: the score system off its
    event, and the maps a win takes off the stage its round names when the
    engine generated its series, else off the map rules of the event.

    Which side of that a fixture falls on is the rule series_rules states: a
    generated series names an entrant, a GNL series names players only."""
    if not match_ids:
        return {}
    generated = (
        select(col(Series.id))
        .where(
            col(Series.match_id) == col(Match.id),
            col(Series.entrant1_id).is_not(None),
        )
        .exists()
    )
    rows = session.execute(
        select(
            col(Match.id),
            col(Season.score_system),
            col(Season.map_rules),
            col(DBEventRound.best_of),
            col(EventStage.best_of),
            generated,
        )
        .join(Season, col(Season.id) == Match.season_id)
        .outerjoin(DBEventRound, col(DBEventRound.id) == col(Match.round_id))
        .outerjoin(EventStage, col(EventStage.id) == col(DBEventRound.stage_id))
        .where(col(Match.id).in_(match_ids))
    ).all()
    return {
        match_id: (
            system or DEFAULT_SYSTEM,
            wins_of(best)
            if made and (best := round_best or stage_best)
            else wins_needed(rules),
        )
        for match_id, system, rules, round_best, stage_best, made in rows
    }


def _scores_by_match(session: Session, scales: dict[int, Scale]) -> MatchScores:
    """The two team scores of every match, summed from its series."""
    by_scale: dict[Scale, list[int]] = {}
    for match_id, scale in scales.items():
        by_scale.setdefault(scale, []).append(match_id)

    scores: MatchScores = {}
    for scale, match_ids in by_scale.items():
        rows = session.execute(
            select(
                col(Series.match_id),
                func.sum(
                    points_case(
                        col(Series.player1_score), col(Series.player2_score), *scale
                    )
                ),
                func.sum(
                    points_case(
                        col(Series.player2_score), col(Series.player1_score), *scale
                    )
                ),
            )
            .where(col(Series.match_id).in_(match_ids))
            .group_by(col(Series.match_id))
        ).all()
        for match_id, team1, team2 in rows:
            scores[match_id] = (int(team1 or 0), int(team2 or 0))
    return scores


def _fill_match(match: MatchPublic, scores: MatchScores) -> None:
    """A match with no result yet stands at 0-0."""
    match.team1_score, match.team2_score = scores.get(match.id, (0, 0))


def _signup_races(
    session: Session, pairs: set[tuple[int, int]]
) -> dict[tuple[int, int], str]:
    """The registered race of every (player, season) pair, in one statement."""
    if not pairs:
        return {}
    rows = session.execute(
        select(
            col(DBUserSeasonSignup.user_id),
            col(DBUserSeasonSignup.season_id),
            col(DBUserSeasonSignup.race),
        ).where(
            tuple_(
                col(DBUserSeasonSignup.user_id), col(DBUserSeasonSignup.season_id)
            ).in_(pairs)
        )
    ).all()
    return {
        (user_id, season_id): race.value for user_id, season_id, race in rows if race
    }


def _entrant_races(
    session: Session, pairs: set[tuple[int, int]]
) -> dict[tuple[int, int], str]:
    """The race of every (player, event) entrant row, in one statement."""
    if not pairs:
        return {}
    rows = session.execute(
        select(
            col(EventEntrant.user_id),
            col(EventEntrant.event_id),
            col(EventEntrant.race),
        ).where(
            tuple_(col(EventEntrant.user_id), col(EventEntrant.event_id)).in_(pairs)
        )
    ).all()
    return {
        (user_id, event_id): race.value
        for user_id, event_id, race in rows
        if user_id and race
    }


def signup_on(
    signup: type[DBUserSeasonSignup], user_id: Mapped[int | None] | ColumnElement[int]
) -> ColumnElement[bool]:
    """The join of a season signup: the player AND the season of the series.
    One key alone reads the race off some other season the player signed up for."""
    return (col(signup.user_id) == user_id) & (col(signup.season_id) == Match.season_id)


def race_of(
    off_race: Mapped[Race | None], signup: type[DBUserSeasonSignup]
) -> ColumnElement[Any]:
    """The race a side played: the off race he reported, else his signup race."""
    return func.coalesce(off_race, col(signup.race))


def clear_kept_off_race(session: Session, row: Series) -> None:
    """Drop an off race that names the race the side signed the season up on.

    The admin edit and the Discord score command both send the whole series
    back, so a stored value has to mean a real exception and nothing else.
    A write that names no off race pays no statement.
    """
    season_id = row.match.season_id if row.match else None
    if season_id is None or not (row.player1_off_race or row.player2_off_race):
        return
    signed = _signup_races(
        session,
        {
            (side, season_id)
            for side in (row.player1_id, row.player2_id)
            if side is not None
        },
    )
    for user_id, field in (
        (row.player1_id, "player1_off_race"),
        (row.player2_id, "player2_off_race"),
    ):
        off_race = fantasy.race_value(getattr(row, field))
        if off_race is not None and off_race == signed.get((user_id, season_id)):
            setattr(row, field, None)


def fill_user_signup_races(
    session: Session, pairs: Iterable[tuple[UserListPublic, int | None]]
) -> None:
    """Fill the signup race and the played-as tag of every player for the
    season he is named with, in one statement."""
    named = [(player, season_id) for player, season_id in pairs if season_id]
    keys = {(player.id, season) for player, season in named}
    rows = (
        session.execute(
            select(
                col(DBUserSeasonSignup.user_id),
                col(DBUserSeasonSignup.season_id),
                col(DBUserSeasonSignup.race),
                col(DBUserSeasonSignup.played_as),
            ).where(
                tuple_(
                    col(DBUserSeasonSignup.user_id), col(DBUserSeasonSignup.season_id)
                ).in_(keys)
            )
        ).all()
        if keys
        else []
    )
    signed = {(row[0], row[1]): row for row in rows}
    for player, season_id in named:
        row = signed.get((player.id, season_id))
        player.signup_race = row.race.value if row and row.race else None
        player.played_as = row.played_as if row else None


def fill_signup_races(
    session: Session,
    rows: Iterable[SeriesPublic | DraftSeriesPublic | None],
    events: dict[int, int] | None = None,
) -> None:
    """Fill the signup race of both players for the season of each row's match,
    then the race each side of a series played. The second one costs no
    statement: it reads the signup race this call just filled.

    A series with no fixture has no season signup, so its two sides take the
    race off the entrant row of the event `events` names for it.
    """
    filled = [row for row in rows if row is not None]
    fill_user_signup_races(
        session,
        [
            (player, row.match.season_id)
            for row in filled
            if row.match
            for player in (row.player1, row.player2)
            if player
        ],
    )
    entered = [
        (player, events[row.id])
        for row in filled
        if not row.match and events and row.id in events
        for player in (row.player1, row.player2)
        if player
    ]
    races = _entrant_races(session, {(player.id, event) for player, event in entered})
    for player, event_id in entered:
        player.signup_race = races.get((player.id, event_id))
    for row in filled:
        # A draft has no result and so no off race, only the signup race
        off1 = row.player1_off_race if isinstance(row, SeriesPublic) else None
        off2 = row.player2_off_race if isinstance(row, SeriesPublic) else None
        row.player1_race = off1 or (row.player1.signup_race if row.player1 else None)
        row.player2_race = off2 or (row.player2.signup_race if row.player2 else None)


def fill_mmrs(session: Session, series_list: Iterable[SeriesPublic | None]) -> None:
    """Rate both sides of every series on the race the row names, in two reads.

    The reduced player of a list answer carries no W3C stats, so the row holds
    the rating itself. Call it after `fill_series`, which names the races. The
    reads are three while the W3Champions season setting is unset, because the
    rule then asks the stats table for the newest stored season.
    """
    # app.services.events imports this module, so its rule comes in on the call
    from app.services.events import race_ratings

    rows = [series for series in series_list if series is not None]
    sides = [
        (player.id, race)
        for row in rows
        for player, race in (
            (row.player1, row.player1_race),
            (row.player2, row.player2_race),
        )
        if player
    ]
    rated = race_ratings(session, sides)
    for row in rows:
        if row.player1 and row.player1_race:
            row.player1_mmr = rated.get((row.player1.id, row.player1_race))
        if row.player2 and row.player2_race:
            row.player2_mmr = rated.get((row.player2.id, row.player2_race))


def fill_series(session: Session, series_list: Iterable[SeriesPublic | None]) -> None:
    """Fill the points of every series, the score of the match it carries, the
    signup race and the season record of its two players."""
    rows = [series for series in series_list if series is not None]
    if not rows:
        return

    resolved = series_rules.fill_rules(session, rows)
    scales: dict[int, Scale] = {}
    events: dict[int, int] = {}
    for series in rows:
        event_id, system, wins = resolved.get(series.id) or (None, *DEFAULT_SCALE)
        if event_id is not None:
            events[series.id] = event_id
        if series.match_id is not None:
            scales[series.match_id] = (system, wins)
        series.player1_points = points(
            series.player1_score, series.player2_score, system, wins
        )
        series.player2_points = points(
            series.player2_score, series.player1_score, system, wins
        )

    scores = _scores_by_match(session, scales)
    for series in rows:
        if series.match:
            _fill_match(series.match, scores)

    fill_signup_races(session, rows, events)

    fill_gnl_stats(
        session,
        [player for series in rows for player in (series.player1, series.player2)],
    )


def fill_matches(session: Session, matches: Iterable[MatchPublic | None]) -> None:
    """Fill the two team scores of every match."""
    rows = [match for match in matches if match is not None]
    if not rows:
        return

    scales = _scales_by_match(session, {match.id for match in rows if match.id})
    scores = _scores_by_match(session, scales)
    for match in rows:
        _fill_match(match, scores)


def _rules_by_season(session: Session, season_ids: set[int]) -> SeasonRules:
    """The scale and the season length of every season, in one statement."""
    if not season_ids:
        return {}
    rows = session.execute(
        select(
            col(Season.id),
            col(Season.score_system),
            col(Season.map_rules),
            col(Season.series_per_round),
            ROUND_COUNT,
        ).where(col(Season.id).in_(season_ids))
    ).all()
    return {
        season_id: (_scale(system, rules), per_week, weeks)
        for season_id, system, rules, per_week, weeks in rows
    }


def _sums_by_team(session: Session, rules: SeasonRules) -> TeamSums:
    """The points for and against, and the series won and lost, of every team
    of every season.

    One statement per scale, grouped by the two teams of a match, so a
    team collects both the matches it holds as team1 and as team2. A series
    goes to the side with more map wins; one with no score counts for neither.
    """
    by_scale: dict[Scale, list[int]] = {}
    for season_id, (scale, _, _) in rules.items():
        by_scale.setdefault(scale, []).append(season_id)

    sums: TeamSums = {}
    for scale, season_ids in by_scale.items():
        rows = session.execute(
            select(
                col(Match.season_id),
                col(Match.team1_id),
                col(Match.team2_id),
                func.sum(
                    points_case(
                        col(Series.player1_score), col(Series.player2_score), *scale
                    )
                ),
                func.sum(
                    points_case(
                        col(Series.player2_score), col(Series.player1_score), *scale
                    )
                ),
                func.sum(
                    case(
                        (col(Series.player1_score) > col(Series.player2_score), 1),
                        else_=0,
                    )
                ),
                func.sum(
                    case(
                        (col(Series.player2_score) > col(Series.player1_score), 1),
                        else_=0,
                    )
                ),
            )
            .join(Series, col(Series.match_id) == Match.id)
            .where(col(Match.season_id).in_(season_ids))
            .group_by(col(Match.season_id), col(Match.team1_id), col(Match.team2_id))
        ).all()
        for season_id, team1_id, team2_id, team1, team2, won1, won2 in rows:
            one, two = int(team1 or 0), int(team2 or 0)
            win1, win2 = int(won1 or 0), int(won2 or 0)
            for team_id, own, opp, won, lost in (
                (team1_id, one, two, win1, win2),
                (team2_id, two, one, win2, win1),
            ):
                entry = sums.setdefault((team_id, season_id), [0, 0, 0, 0])
                entry[0] += own
                entry[1] += opp
                entry[2] += won
                entry[3] += lost
    return sums


def season_winners(session: Session, season_ids: set[int]) -> dict[int, int]:
    """The team that tops each of those seasons' derived standings.

    Ties break by fewer points against, then the older team, matching what
    the standings read as first place. The caller decides whether the season
    is finished; a season still running has a leader, not a champion.
    """
    if not season_ids:
        return {}
    rules = _rules_by_season(session, season_ids)
    sums = _sums_by_team(session, rules)
    best: dict[int, tuple[int, int, int]] = {}
    for (team_id, season_id), (final, against, *_) in sums.items():
        key = (-final, against, team_id)
        if season_id not in best or key < best[season_id]:
            best[season_id] = key
    return {season_id: team_id for season_id, (_, _, team_id) in best.items()}


def _season_infos(
    teams: Iterable[TeamPublic | None],
) -> list[tuple[int, SeasonInfoPublic]]:
    """Every seasons_info row of those teams, paired with the team that holds it."""
    return [
        (team.id, info)
        for team in teams
        if team is not None
        for info in team.seasons_info
        if info.season_id is not None
    ]


def fill_season_labels(session: Session, teams: Iterable[TeamPublic | None]) -> None:
    """Name the event and its league on every seasons_info row, in one statement.

    A team page labels its season tabs from these, so the count does not grow
    with the number of teams or of seasons in the answer.
    """
    infos = [info for _, info in _season_infos(teams)]
    if not infos:
        return

    rows = session.execute(
        select(col(Season.id), col(Season.name), LEAGUE_SHORT_NAME).where(
            col(Season.id).in_({info.season_id for info in infos})
        )
    ).all()
    labels = {season_id: (name, short) for season_id, name, short in rows}
    for info in infos:
        info.name, info.league_short_name = labels.get(info.season_id, (None, None))


def fill_standings(session: Session, teams: Iterable[TeamPublic | None]) -> None:
    """Fill final_score, points_against, points_available and the series record
    on every seasons_info row of every team."""
    infos = _season_infos(teams)
    if not infos:
        return

    rules = _rules_by_season(
        session, {info.season_id for _, info in infos if info.season_id is not None}
    )
    sums = _sums_by_team(session, rules)

    for team_id, info in infos:
        scale, per_week, weeks = rules.get(info.season_id, (DEFAULT_SCALE, None, None))
        final, against, won, lost = sums.get((team_id, info.season_id), [0, 0, 0, 0])
        info.final_score = final
        info.points_against = against
        info.series_won = won
        info.series_lost = lost
        info.points_available = (
            per_week * weeks * max_points(*scale) - final - against
            if per_week is not None and weeks is not None
            else None
        )


class GnlTally(NamedTuple):
    """What one player took from one season: series he stood in, series won
    and series lost. A drawn or open series counts as a game and pays
    neither."""

    games: int
    wins: int
    losses: int


def _gnl_tallies(
    session: Session, user_ids: set[int], season_ids: set[int]
) -> dict[tuple[int, int], GnlTally]:
    """The season record of every named player, in one statement.

    A series counts for both of its players, so the two sides union before the
    grouping. It counts as a game once the player stands in it, and pays a win
    or a loss once both map scores are in and they are not both zero. The maps
    a win takes come off the season, so every other scored series is a loss.
    """
    wins = wins_needed_sql(col(Season.map_rules)).label("wins")
    sides = union_all(
        select(
            col(Series.player1_id).label("user_id"),
            col(Match.season_id).label("season_id"),
            col(Series.player1_score).label("own"),
            col(Series.player2_score).label("opp"),
            wins,
        )
        .join(Match, col(Match.id) == Series.match_id)
        .join(Season, col(Season.id) == Match.season_id),
        select(
            col(Series.player2_id),
            col(Match.season_id),
            col(Series.player2_score),
            col(Series.player1_score),
            wins,
        )
        .join(Match, col(Match.id) == Series.match_id)
        .join(Season, col(Season.id) == Match.season_id),
    ).subquery()

    own, opp, wins = sides.c.own, sides.c.opp, sides.c.wins
    scored = own.is_not(None) & opp.is_not(None) & ~((own == 0) & (opp == 0))
    rows = session.execute(
        select(
            sides.c.user_id,
            sides.c.season_id,
            func.count(),
            # count() skips the null a case with no else leaves behind
            func.count(case((scored & (own == wins), 1))),
            func.count(case((scored & (own != wins), 1))),
        )
        .where(sides.c.user_id.in_(user_ids), sides.c.season_id.in_(season_ids))
        .group_by(sides.c.user_id, sides.c.season_id)
    ).all()
    return {
        (user_id, season_id): GnlTally(int(games), int(wins), int(losses))
        for user_id, season_id, games, wins, losses in rows
    }


def _gnl_matchups(
    session: Session, user_ids: set[int], season_ids: set[int]
) -> dict[tuple[int, int], list[str | None]]:
    """The race every opponent of every named player registered on, in one
    statement that answers one row per player and season.

    The opponent is the other player of the series, so the two sides union
    again. Each entry carries its playday and series id, and the list sorts on
    them, so it reads in the order the season was played. An opponent the
    season holds no signup for reads null, and the entry stays in the list so
    it keeps the length of the season.
    """
    signup1, signup2 = aliased(DBUserSeasonSignup), aliased(DBUserSeasonSignup)
    sides = union_all(
        select(
            col(Series.player1_id).label("user_id"),
            col(Match.season_id).label("season_id"),
            col(Match.playday).label("playday"),
            col(Series.id).label("series_id"),
            race_of(col(Series.player2_off_race), signup1).label("race"),
        )
        .join(Match, col(Match.id) == Series.match_id)
        .join(signup1, signup_on(signup1, col(Series.player2_id)), isouter=True),
        select(
            col(Series.player2_id),
            col(Match.season_id),
            col(Match.playday),
            col(Series.id),
            race_of(col(Series.player1_off_race), signup2),
        )
        .join(Match, col(Match.id) == Series.match_id)
        .join(signup2, signup_on(signup2, col(Series.player1_id)), isouter=True),
    ).subquery()

    # "playday:series id:race", the race empty when the opponent has none
    entry = (
        cast(sides.c.playday, String)
        + ":"
        + cast(sides.c.series_id, String)
        + ":"
        + func.coalesce(cast(sides.c.race, String), "")
    )
    rows = session.execute(
        select(sides.c.user_id, sides.c.season_id, func.aggregate_strings(entry, ","))
        .where(sides.c.user_id.in_(user_ids), sides.c.season_id.in_(season_ids))
        .group_by(sides.c.user_id, sides.c.season_id)
    ).all()

    history: dict[tuple[int, int], list[str | None]] = {}
    for user_id, season_id, joined in rows:
        entries = sorted(
            (int(playday), int(series_id), race)
            for playday, series_id, race in (
                item.split(":") for item in joined.split(",")
            )
        )
        history[(user_id, season_id)] = [
            fantasy.race_value(Race[race]) if race else None for _, _, race in entries
        ]
    return history


def fill_trophies(session: Session, users: Iterable[UserPublic | None]) -> None:
    """Fill the trophies of every user: the seasons his team won and the events
    that awarded him a first place.

    A season still running has a leader, not a champion, so only a complete
    season pays. The phase of every season they played is one statement, and
    the awards of every other event are one more.
    """
    rows = [user for user in users if user is not None]
    if not rows:
        return
    shelves = _season_trophies(session, rows)
    won_events = {trophy.season_id for shelf in shelves.values() for trophy in shelf}
    awarded = _award_trophies(session, rows, won_events)
    for user in rows:
        user.trophies = sorted(
            shelves.get(user.id, []) + awarded.get(user.id, []),
            # newest event first, the way a shelf reads
            key=lambda trophy: -(trophy.season_id or 0),
        )


def _award_trophies(
    session: Session, users: list[UserPublic], won_events: set[int | None]
) -> dict[int, list[TrophyPublic]]:
    """The first place of every closed event that awarded one of these players.

    An event whose championship the season read already derives pays no second
    row, so no event engraves the same player twice.
    """
    rows = session.execute(
        select(EventAward, Season, Team)
        .join(Season, col(Season.id) == EventAward.event_id)
        .join(Team, col(Team.id) == EventAward.team_id, isouter=True)
        .where(
            col(EventAward.user_id).in_({user.id for user in users}),
            col(EventAward.place) == 1,
        )
    ).all()
    shelves: dict[int, list[TrophyPublic]] = {}
    for award, event, team in rows:
        if award.user_id is None or award.event_id in won_events:
            continue
        shelves.setdefault(award.user_id, []).append(
            TrophyPublic(
                title=f"{event.name} {award.title}",
                season_id=award.event_id,
                season_name=event.name,
                league_short_name=event.league_short_name,
                team_id=award.team_id,
                team_name=team.name if team is not None else None,
                team_icon_url=team.icon_url if team is not None else None,
            )
        )
    return shelves


def _season_trophies(
    session: Session, rows: list[UserPublic]
) -> dict[int, list[TrophyPublic]]:
    """The championship of every finished season one of these players won."""
    roster = {
        (stat.team_id, stat.season_id)
        for user in rows
        for stat in user.gnl_stats
        if stat.team_id is not None and stat.season_id is not None
    }
    if not roster:
        return {}

    seasons = {
        ident(season): season
        for season in session.scalars(
            select(Season).where(col(Season.id).in_({sid for _, sid in roster}))
        )
    }
    progress = progress_by_seasons(session, seasons.values())
    winners = season_winners(
        session,
        {sid for sid in seasons if progress[sid].phase == "complete"},
    )
    won = {(team_id, sid) for sid, team_id in winners.items()}
    teams = {
        ident(team): team
        for team in session.scalars(
            select(Team).where(col(Team.id).in_(set(winners.values())))
        )
    }

    shelves: dict[int, list[TrophyPublic]] = {}
    for user in rows:
        played = {(stat.team_id, stat.season_id) for stat in user.gnl_stats}
        shelves[user.id] = [
            TrophyPublic(
                title=f"{seasons[season_id].name} Champion",
                season_id=season_id,
                season_name=seasons[season_id].name,
                league_short_name=seasons[season_id].league_short_name,
                team_id=team_id,
                team_name=teams[team_id].name,
                team_icon_url=teams[team_id].icon_url,
            )
            for team_id, season_id in won
            if (team_id, season_id) in played
        ]
    return shelves


def fill_gnl_stats(session: Session, users: Iterable[UserPublic | None]) -> None:
    """Fill games, wins, losses and matchup_history on every gnl_stats row of
    every user."""
    rows = [
        stat
        for user in users
        if user is not None
        for stat in user.gnl_stats
        if stat.user_id is not None and stat.season_id is not None
    ]
    if not rows:
        return

    user_ids = {stat.user_id for stat in rows if stat.user_id is not None}
    season_ids = {stat.season_id for stat in rows if stat.season_id is not None}
    tallies = _gnl_tallies(session, user_ids, season_ids)
    matchups = _gnl_matchups(session, user_ids, season_ids)

    for stat in rows:
        key = (stat.user_id, stat.season_id)
        stat.games, stat.wins, stat.losses = tallies.get(key, GnlTally(0, 0, 0))
        stat.matchup_history = matchups.get(key, [])


def _career_players(
    system_seasons: list[int], focus: tuple[set[int], set[str]] | None = None
) -> CTE:
    """The totals of every player who stands in a series, one row each.

    A series counts for both of its players, so the two sides union before the
    grouping. A series with no map score still names the season the player
    stood in, and pays nothing.
    """
    sides = union_all(
        select(
            col(Series.player1_id).label("user_id"),
            col(Match.season_id).label("season_id"),
            func.coalesce(Series.player1_score, 0).label("own"),
            func.coalesce(Series.player2_score, 0).label("opp"),
        ).join(Match, col(Match.id) == Series.match_id),
        select(
            col(Series.player2_id),
            col(Match.season_id),
            func.coalesce(Series.player2_score, 0),
            func.coalesce(Series.player1_score, 0),
        ).join(Match, col(Match.id) == Series.match_id),
    ).subquery()

    own, opp = sides.c.own, sides.c.opp
    season_query = (
        select(
            sides.c.user_id,
            sides.c.season_id,
            func.sum(case((or_(own != 0, opp != 0), 1), else_=0)).label("played"),
            func.sum(case((own > opp, 1), else_=0)).label("won"),
            func.sum(case((opp > own, 1), else_=0)).label("lost"),
            func.sum(own).label("games_won"),
            func.sum(opp).label("games_lost"),
        )
        .where(sides.c.user_id.is_not(None))
        .group_by(sides.c.user_id, sides.c.season_id)
    )
    if focus is not None:
        user_ids, names = focus
        matching_ids = select(col(User.id)).where(col(User.name).in_(names))
        season_query = season_query.where(
            or_(sides.c.user_id.in_(user_ids), sides.c.user_id.in_(matching_ids))
        )
    seasons = season_query.subquery()

    def total(value: SQLColumnExpression[int]) -> ColumnElement[int]:
        # Postgres sums a bigint to a numeric, and the division needs an integer
        return cast(func.sum(value), BigInteger)

    score = career.season_score_sql(
        seasons.c.won, seasons.c.played, seasons.c.season_id, system_seasons
    )
    return (
        select(
            seasons.c.user_id,
            total(seasons.c.won).label("series_won"),
            total(seasons.c.lost).label("series_lost"),
            total(seasons.c.games_won).label("games_won"),
            total(seasons.c.games_lost).label("games_lost"),
            func.count(seasons.c.season_id).label("seasons"),
            total(seasons.c.played).label("played"),
            total(score).label("score"),
        )
        .group_by(seasons.c.user_id)
        .cte("career_player")
    )


_HISTORICAL = (
    "historical_rating",
    "historical_series_won",
    "historical_series_lost",
    "historical_games_won",
    "historical_games_lost",
    "historical_seasons_played",
)


def _career_rows(player: CTE, stored_ids: set[int] | None = None) -> Subquery:
    """Every career row of the league, and the player whose series it counts.

    A stored row finds its player by user id. A row whose user holds no series
    finds him by the name it carries, unless a row already stands for him by
    user id, or an earlier row by name. A player who has played and holds no
    row stands as a row of his own, with a null id and no historical baseline.
    """
    source: FromClause = getattr(PlayerCareerStats, "__table__")  # noqa: B009
    if stored_ids is not None:
        source = select(source).where(source.c.id.in_(stored_ids)).subquery()
    stored = source.c
    tallied = select(player.c.user_id)
    direct = and_(stored.user_id.is_not(None), stored.user_id.in_(tallied))
    claimed = select(stored.user_id).where(stored.user_id.in_(tallied))
    # Two players of one name leave the row to the smaller user id
    namesake = aliased(User)
    by_name = (
        select(func.min(namesake.id))
        .where(col(namesake.name) == stored.player_name, col(namesake.id).in_(tallied))
        .scalar_subquery()
    )
    candidates = select(
        stored.id,
        stored.user_id,
        stored.player_name,
        *(stored[name] for name in _HISTORICAL),
        case((direct, stored.user_id)).label("direct_id"),
        case((and_(~direct, by_name.not_in(claimed)), by_name)).label("candidate"),
    ).subquery()
    first = func.row_number().over(
        partition_by=candidates.c.candidate, order_by=candidates.c.id
    )
    ranked = select(candidates, first.label("rank")).subquery()
    rows = select(
        ranked.c.id,
        ranked.c.user_id,
        ranked.c.player_name,
        *(ranked.c[name] for name in _HISTORICAL),
        func.coalesce(
            ranked.c.direct_id, case((ranked.c.rank == 1, ranked.c.candidate))
        ).label("player_id"),
    ).cte("career_stored")

    unclaimed = (
        select(
            cast(null(), Integer),
            player.c.user_id,
            col(User.name),
            *(cast(null(), Integer) for _ in _HISTORICAL),
            player.c.user_id,
        )
        .join(User, col(User.id) == player.c.user_id)
        .where(
            player.c.played > 0,
            player.c.user_id.not_in(
                select(rows.c.player_id).where(rows.c.player_id.is_not(None))
            ),
        )
    )
    return union_all(select(rows), unclaimed).subquery("career_row")


def _career_totals(
    system_seasons: list[int],
    stored_ids: set[int] | None = None,
    focus: tuple[set[int], set[str]] | None = None,
) -> Subquery:
    """Every career row with its baseline and the nine totals, one row each."""
    player = _career_players(system_seasons, focus)
    row = _career_rows(player, stored_ids)

    def plus(historical: str, name: str) -> ColumnElement[int]:
        return func.coalesce(row.c[historical], 0) + func.coalesce(player.c[name], 0)

    series_won = plus("historical_series_won", "series_won")
    series_lost = plus("historical_series_lost", "series_lost")
    games_won = plus("historical_games_won", "games_won")
    games_lost = plus("historical_games_lost", "games_lost")
    return (
        select(
            row.c.id,
            row.c.user_id,
            row.c.player_name,
            *(row.c[name] for name in _HISTORICAL),
            career.rating_sql(
                row.c.historical_rating,
                func.coalesce(player.c.score, 0),
                system_seasons,
            ).label("rating"),
            series_won.label("series_won"),
            series_lost.label("series_lost"),
            games_won.label("games_won"),
            games_lost.label("games_lost"),
            plus("historical_seasons_played", "seasons").label("seasons_played"),
            career.winrate_sql(series_won, series_lost).label("series_winrate"),
            career.winrate_sql(games_won, games_lost).label("games_winrate"),
        )
        .select_from(row.outerjoin(player, player.c.user_id == row.c.player_id))
        .subquery("career_totals")
    )


def _system_seasons(session: Session) -> list[int]:
    """The seasons the league has played, in the order the decay applies."""
    season_ids = session.scalars(
        select(col(Match.season_id))
        .join(Series, col(Series.match_id) == Match.id)
        .distinct()
    ).all()
    return sorted(season_id for season_id in season_ids if season_id is not None)


def _career_public(totals: Any, user: User | None) -> PlayerCareerStatsPublic:  # noqa: ANN401
    """One row of the career statement as its public model."""
    return PlayerCareerStatsPublic(
        id=totals.id,
        user_id=totals.user_id,
        player_name=totals.player_name,
        user=UserReduced.from_user_reduced(user) if user else None,
        **{name: getattr(totals, name) for name in _HISTORICAL},
        rating=totals.rating,
        series_won=totals.series_won,
        series_lost=totals.series_lost,
        games_won=totals.games_won,
        games_lost=totals.games_lost,
        seasons_played=totals.seasons_played,
        series_winrate=totals.series_winrate / 100,
        games_winrate=totals.games_winrate / 100,
        avg_series_per_season=career.per_season(
            totals.series_won + totals.series_lost, totals.seasons_played
        ),
    )


def fill_career(
    session: Session, stats: Iterable[PlayerCareerStatsPublic | None]
) -> None:
    """Fill the nine career totals of every stored row, reading only those rows."""
    rows = {row.id: row for row in stats if row is not None and row.id is not None}
    if not rows:
        return
    focus = (
        {row.user_id for row in rows.values() if row.user_id is not None},
        {row.player_name for row in rows.values() if row.player_name is not None},
    )
    totals = _career_totals(_system_seasons(session), set(rows), focus)
    for found in session.execute(select(totals).where(totals.c.id.in_(rows))).all():
        filled = _career_public(found, None)
        for name in _TOTALS:
            setattr(rows[found.id], name, getattr(filled, name))


_TOTALS = (
    "rating",
    "series_won",
    "series_lost",
    "games_won",
    "games_lost",
    "seasons_played",
    "series_winrate",
    "games_winrate",
    "avg_series_per_season",
)

CareerSort = Literal[
    "name",
    "mapped",
    "rating",
    "series_won",
    "series_lost",
    "series_winrate",
    "games_winrate",
    "games_won",
    "games_lost",
    "seasons_played",
]

# The names a career list sorts by, and the SQL key each one reads. The name
# key takes the career row and the name of the user it carries.
CAREER_SORTS: dict[CareerSort, Callable[[Any, ColumnElement[Any]], Any]] = {
    "name": lambda row, name: name,
    "mapped": lambda row, name: case((row.user_id.is_not(None), 1), else_=0),
    "rating": lambda row, name: row.rating,
    "series_won": lambda row, name: row.series_won,
    "series_lost": lambda row, name: row.series_lost,
    "series_winrate": lambda row, name: row.series_winrate,
    "games_won": lambda row, name: row.games_won,
    "games_lost": lambda row, name: row.games_lost,
    "games_winrate": lambda row, name: row.games_winrate,
    "seasons_played": lambda row, name: row.seasons_played,
}


def career_page(
    session: Session,
    search: str = "",
    *,
    sort: CareerSort | None = None,
    order: SortOrder = "asc",
    limit: int | None = None,
    offset: int = 0,
) -> tuple[list[PlayerCareerStatsPublic], int]:
    """One page of the career rows of the league, and the count of them all.

    The database derives the totals, keeps the rows that match search, sorts
    and pages them, so the answer reads only the rows of the page.

    search keeps the rows whose player name or user name holds it, without
    case, before the count and the page. With no sort the rating orders the
    rows; sort names a key of CAREER_SORTS and order turns that key alone
    around. A row with no id closes its tie, and the ids break the rest, so
    both directions page the same rows.
    """
    totals = _career_totals(_system_seasons(session))
    row = totals.c
    name = func.lower(func.coalesce(User.name, row.player_name))
    if session.get_bind().dialect.name == "postgresql":
        # Byte order is code point order, the order Python sorts strings in
        name = name.collate("C")

    statement = select(totals, User, func.count().over().label("total")).outerjoin(
        User, col(User.id) == row.user_id
    )
    if search:
        needle = search.lower()
        statement = statement.where(
            or_(
                func.lower(row.player_name).contains(needle, autoescape=True),
                func.lower(User.name).contains(needle, autoescape=True),
            )
        )

    tiebreak = (case((row.id.is_(None), 1), else_=0), row.id, row.user_id)
    if sort is None:
        keys = (row.rating.desc(), *tiebreak)
    else:
        key = CAREER_SORTS[sort](row, name)
        keys = (key.desc() if order == "desc" else key.asc(), *tiebreak)
    found = session.execute(statement.order_by(*keys).offset(offset).limit(limit)).all()
    if found:
        total = found[0].total
    elif offset:
        # A page past the end holds no row to carry the count
        total = session.scalar(select(func.count()).select_from(statement.subquery()))
    else:
        total = 0
    return [_career_public(item, item.User) for item in found], total or 0


def fantasy_series(
    session: Session, season_ids: set[int]
) -> dict[int, dict[int | None, list[fantasy.Series]]]:
    """The series of every named season, by season and by week, in one statement.

    The fantasy rules read the map scores and the two races, so the players join
    in as columns rather than load as objects. A side counts on the race he
    played: the off race of the series, else the race he signed the season up on.
    """
    if not season_ids:
        return {}

    player1, player2 = aliased(User), aliased(User)
    signup1, signup2 = aliased(DBUserSeasonSignup), aliased(DBUserSeasonSignup)
    rows = session.execute(
        select(
            col(Match.season_id),
            col(Match.playday),
            col(Series.player1_id),
            col(player1.name),
            race_of(col(Series.player1_off_race), signup1),
            col(Series.player2_id),
            col(player2.name),
            race_of(col(Series.player2_off_race), signup2),
            col(Series.player1_score),
            col(Series.player2_score),
            col(Season.map_rules),
        )
        .join(Match, col(Match.id) == Series.match_id)
        .join(Season, col(Season.id) == Match.season_id)
        .join(player1, col(player1.id) == Series.player1_id, isouter=True)
        .join(player2, col(player2.id) == Series.player2_id, isouter=True)
        .join(signup1, signup_on(signup1, col(Series.player1_id)), isouter=True)
        .join(signup2, signup_on(signup2, col(Series.player2_id)), isouter=True)
        .where(col(Match.season_id).in_(season_ids))
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
        map_rules,
    ) in rows:
        weeks = by_season.setdefault(season_id, {})
        weeks.setdefault(week, []).append(
            fantasy.Series(
                week=week,
                player1=fantasy.Player(one_id, one_name, fantasy.race_value(one_race)),
                player2=fantasy.Player(two_id, two_name, fantasy.race_value(two_race)),
                player1_score=one_score,
                player2_score=two_score,
                wins=wins_needed(map_rules),
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
            col(FantasyBet.user_id),
            col(FantasyBet.season_id),
            col(FantasyBet.id),
            col(FantasyBet.bet_points),
            col(FantasyBet.winner_id),
            col(winner.name),
            col(Match.playday),
            col(Series.player1_id),
            col(player1.name),
            col(Series.player2_id),
            col(player2.name),
            col(Series.player1_score),
            col(Series.player2_score),
            col(Season.map_rules),
        )
        .join(Series, col(Series.id) == FantasyBet.series_id)
        .join(Match, col(Match.id) == Series.match_id, isouter=True)
        .join(Season, col(Season.id) == Match.season_id, isouter=True)
        .join(winner, col(winner.id) == FantasyBet.winner_id, isouter=True)
        .join(player1, col(player1.id) == Series.player1_id, isouter=True)
        .join(player2, col(player2.id) == Series.player2_id, isouter=True)
        .where(
            col(FantasyBet.user_id).in_(captains),
            col(FantasyBet.season_id).in_(season_ids),
        )
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
        map_rules,
    ) in rows:
        by_captain.setdefault((user_id, season_id), []).append(
            fantasy.Bet(
                points=bet_points,
                winner_id=winner_id,
                winner_name=winner_name,
                series=fantasy.Series(
                    week=week,
                    player1=fantasy.Player(one_id, one_name, None),
                    player2=fantasy.Player(two_id, two_name, None),
                    player1_score=one_score,
                    player2_score=two_score,
                    wins=wins_needed(map_rules),
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
            series.player1_race,
        ),
        player2=fantasy.Player(
            series.player2_id,
            series.player2.name if series.player2 else None,
            series.player2_race,
        ),
        player1_score=series.player1_score,
        player2_score=series.player2_score,
        wins=wins_needed(
            series.match.season.map_rules
            if series.match and series.match.season
            else None
        ),
    )


def public_bet(bet: FantasyBetPublic) -> fantasy.Bet | None:
    """One answered bet, as the fantasy rules read it; None without its series."""
    series = public_series(bet.series)
    if series is None:
        return None
    return fantasy.Bet(
        points=bet.bet_points,
        winner_id=bet.winner_id,
        winner_name=bet.winner.name if bet.winner else None,
        series=series,
    )


def _season_weeks(rules: SeasonRules, season_id: int | None) -> int | None:
    """How many weeks the season is played over."""
    return rules.get(season_id, (DEFAULT_SCALE, None, None))[2]


def _drafted_standing(
    rules: SeasonRules, sums: TeamSums, team_id: int | None, season_id: int | None
) -> fantasy.Standing | None:
    """What the drafted team stands at in the season of the fantasy team.

    The list answer carries no team name, and only the breakdown reads one.
    """
    if team_id is None or season_id is None:
        return None
    scale, per_week, weeks = rules.get(season_id, (DEFAULT_SCALE, None, None))
    final, against = sums.get((team_id, season_id), [0, 0, 0, 0])[:2]
    available = (
        per_week * weeks * max_points(*scale) - final - against
        if per_week is not None and weeks is not None
        else 0
    )
    return fantasy.Standing(team_id, None, None, final, against, available)


def _grind_by_season(
    session: Session, rows: list[FantasyTeamPublic]
) -> dict[int, dict[int, int]]:
    """The achievement points of every team, per season that offers the grind
    pick and holds one in this batch. No pick costs no statement."""
    # app.services.ladder reads this module through app.services.users
    from app.services.ladder import team_achievement_points

    picked = {
        team.season_id
        for team in rows
        if team.grind_team_id is not None and team.season_id is not None
    }
    if not picked:
        return {}
    offered = picked & set(
        session.scalars(
            select(col(Season.id)).where(
                col(Season.id).in_(picked), col(Season.fantasy_grind)
            )
        )
    )
    return {
        season_id: team_achievement_points(session, season_id) for season_id in offered
    }


def _grind(
    achievement_points: dict[int, dict[int, int]],
    team_id: int | None,
    season_id: int | None,
) -> fantasy.Grind | None:
    """The grind pick of one fantasy team. The list answer carries no team
    name, and only the breakdown reads one."""
    by_team = achievement_points.get(season_id) if season_id is not None else None
    if team_id is None or not by_team:
        return None
    rank, points = fantasy.grind_points(by_team, team_id)
    return fantasy.Grind(
        team_id, None, by_team.get(team_id, 0), rank, len(by_team), points
    )


def fill_fantasy_teams(
    session: Session, teams: Iterable[FantasyTeamPublic | None]
) -> None:
    """Fill the seven score fields of every fantasy team and the signup race of
    every drafted player, each against the season the team names."""
    rows = [team for team in teams if team is not None]
    if not rows:
        return

    fill_user_signup_races(
        session,
        [(player, team.season_id) for team in rows for player in team.drafted_players],
    )
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
    grinds = _grind_by_season(session, rows)

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
            round_count=_season_weeks(rules, season_id),
            grind=_grind(grinds, team.grind_team_id, season_id),
        )
        team.player_points = scores["player_points"]
        team.bench_points = scores["bench_points"]
        team.team_points = scores["team_points"]
        team.race_points = scores["race_points"]
        team.bet_points = scores["bet_points"]
        team.grind_points = scores["grind_points"]
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
