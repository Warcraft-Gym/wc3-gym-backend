"""The achievement rules of core.achievements as SQL.

Every rule is a select of (user_id, rule_id, achieved_at, extra) over the
scoped matches, and one union answers every player at once: at most 24 rows a
player, whatever the number of matches behind them. `extra` is the kill count
of duck_hunting, the win count of a race rule, and 0 for the other rules,
which pay a flat price.

The shapes are read off the wc3.no bundle the catalogue was read off: an nth
result, a run of results, an MMR value, the race beaten most, a set of maps,
a UTC day, a win over a tagged opponent, and a running sum of ladder points.

tests/achievement_oracle.py is the same rule set in Python and
tests/test_achievement_parity.py runs the two over the same random matches.
"""

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import replace
from datetime import datetime
from operator import itemgetter
from typing import Any

from sqlalchemy import (
    CTE,
    Case,
    ColumnElement,
    Row,
    Select,
    SQLColumnExpression,
    and_,
    case,
    extract,
    false,
    func,
    literal,
    or_,
    select,
    union_all,
)
from sqlalchemy.orm import Session as OrmSession
from sqlmodel import col

from app.core import ladder
from app.core.achievements import (
    ACHIEVEMENTS,
    ADDICTED,
    DATS_FAKT_AP,
    DOUBLE_UP,
    DUCK_HUNTING,
    ELITE,
    ELITE_MMR,
    FALLING_STAR,
    HOLIDAY,
    HOLIDAY_MAPS,
    I_AM_THE_CAPTAIN_NOW,
    JOIN_THEM,
    LADDER_GOAL,
    LADDER_GOAL_REACHED,
    LADDER_MAPS,
    LONG_GAME_S,
    LOSE_FIRST,
    NEW_MAPS,
    NEWBIE,
    RACE_ACHIEVEMENTS,
    RACE_IDS,
    RISING_STAR,
    SAD_TROMBONE,
    WIN_EVERY_MAP,
    WIN_FIRST,
    WIN_STREAK,
    WIN_STREAK_2,
    WINNER_WINNER,
    WINTER,
    WINTER_MAPS,
    Achievement,
    PaidSet,
)
from app.models.enums import Race
from app.models.w3c_ladder_match import W3CLadderMatch

# The rules that pay per match: what one adds to the price, and how it reads
VARIABLE = {
    DUCK_HUNTING.id: (5, " - {} kill(s)"),
    **{rule.id: (1, " - {} wins!") for rule in RACE_ACHIEVEMENTS.values()},
}

# The catalogue by the id the statement answers
BY_ID = {rule.id: rule for rule in ACHIEVEMENTS}

# The race the badge names, and the tie the bundle breaks by the lowest race id
RACE_RULES = {Race[code]: rule.id for code, rule in RACE_ACHIEVEMENTS.items()}
RACE_ORDER = {Race[code]: number for code, number in RACE_IDS.items()}

# Lifetime badges count from this w3champions season on
LIFETIME_FROM_W3C_SEASON = 26

# Ten wins do not pay; the eleventh does, and it dates the badge
RACE_WINS = 10
# A day of this many matches is an addiction
ADDICTED_GAMES = 30
# What one day has to move the MMR by
DAY_MMR = 100


def earned(
    session: OrmSession,
    scope: Sequence[ColumnElement[bool]],
    paid: PaidSet,
    opponents: Mapping[int, frozenset[str]],
    captains: frozenset[str],
    captain_ids: Sequence[int],
    lifetime: bool,
) -> dict[int, list[Achievement]]:
    """Every player's achievements over the scope, oldest first.

    `paid` is what this scope pays for each rule and a rule it does not name
    is not evaluated; `opponents` are the tags of the players on other teams,
    per player; `captains` the tags of the season's captains and `captain_ids`
    the players who are captains themselves, who the captain rule skips.
    `lifetime` is the scope that spans seasons, which starts its rules at
    LIFETIME_FROM_W3C_SEASON.
    """
    queries = _queries(_scoped(scope, lifetime), opponents, captains, captain_ids)
    wanted = [(ids, query) for ids, query in queries if paid.keys() & set(ids)]
    if not wanted:
        return {}
    order = {rule_id: n for n, (ids, _) in enumerate(wanted) for rule_id in ids}
    rows = session.execute(union_all(*(_member(query) for _, query in wanted))).all()
    return _badges(rows, paid, order)


def _badges(
    rows: Iterable[Row[Any]], paid: PaidSet, order: Mapping[str, int]
) -> dict[int, list[Achievement]]:
    """The badges these rows read as, per player, oldest first.

    Two badges of one instant keep the order the rules are evaluated in.
    """
    found: dict[int, list[tuple[datetime, int, Achievement]]] = {}
    for row in rows:
        price = paid.get(row.rule_id)
        if price is None:
            continue
        rate, suffix = VARIABLE.get(row.rule_id, (0, ""))
        rule = BY_ID[row.rule_id]
        badge = replace(
            rule,
            points=price + rate * row.extra,
            description=rule.description + suffix.format(row.extra),
            achieved_at=row.achieved_at,
        )
        found.setdefault(row.user_id, []).append(
            (row.achieved_at, order[row.rule_id], badge)
        )
    return {
        user_id: [badge for _, _, badge in sorted(items, key=itemgetter(0, 1))]
        for user_id, items in found.items()
    }


def _queries(
    rows: CTE,
    opponents: Mapping[int, frozenset[str]],
    captains: frozenset[str],
    captain_ids: Sequence[int],
) -> list[tuple[tuple[str, ...], Select[Any]]]:
    """Every rule as one statement, in the order the rules are evaluated in.

    A rule whose inputs are empty is dropped: no roster means no duck and no
    captain to beat.
    """
    queries: list[tuple[tuple[str, ...], Select[Any]]] = [
        ((WIN_FIRST.id,), _first_match(rows, True, WIN_FIRST.id)),
        ((LOSE_FIRST.id,), _first_match(rows, False, LOSE_FIRST.id)),
        ((WINNER_WINNER.id,), _nth_result(rows, True, 100, WINNER_WINNER.id)),
        ((SAD_TROMBONE.id,), _nth_result(rows, False, 100, SAD_TROMBONE.id)),
        ((ELITE.id,), _mmr_reaches(rows, ELITE_MMR, ELITE.id)),
        ((DATS_FAKT_AP.id,), _streak(rows, False, 10, DATS_FAKT_AP.id)),
        ((WIN_STREAK.id,), _streak(rows, True, 5, WIN_STREAK.id)),
        ((WIN_STREAK_2.id,), _streak(rows, True, 10, WIN_STREAK_2.id)),
    ]
    if any(opponents.values()):
        queries.append(
            (
                (DUCK_HUNTING.id,),
                _tagged_win(
                    rows, _ducks(rows, opponents), DUCK_HUNTING.id, func.count()
                ),
            )
        )
    if captains:
        queries.append(
            (
                (I_AM_THE_CAPTAIN_NOW.id,),
                _tagged_win(
                    rows,
                    and_(
                        rows.c.tag.in_(captains),
                        rows.c.user_id.not_in(captain_ids),
                    ),
                    I_AM_THE_CAPTAIN_NOW.id,
                    literal(0),
                ),
            )
        )
    queries += [
        (tuple(RACE_RULES.values()), _race_wins(rows, RACE_WINS)),
        ((HOLIDAY.id,), _map_set(rows, HOLIDAY_MAPS, HOLIDAY.id)),
        ((WINTER.id,), _map_set(rows, WINTER_MAPS, WINTER.id)),
        ((NEWBIE.id,), _map_set(rows, NEW_MAPS, NEWBIE.id)),
        ((WIN_EVERY_MAP.id,), _map_set(rows, LADDER_MAPS, WIN_EVERY_MAP.id)),
        ((JOIN_THEM.id,), _long_both(rows, LONG_GAME_S, JOIN_THEM.id)),
        ((ADDICTED.id,), _day_count(rows, ADDICTED_GAMES, ADDICTED.id)),
        ((RISING_STAR.id,), _day_mmr(rows, DAY_MMR, RISING_STAR.id)),
        ((FALLING_STAR.id,), _day_mmr(rows, -DAY_MMR, FALLING_STAR.id)),
        ((LADDER_GOAL_REACHED.id,), _goal(rows, LADDER_GOAL, LADDER_GOAL_REACHED.id)),
        ((DOUBLE_UP.id,), _goal(rows, LADDER_GOAL * 2, DOUBLE_UP.id)),
    ]
    return queries


def _scoped(scope: Sequence[ColumnElement[bool]], lifetime: bool) -> CTE:
    """The matches the rules read, with the values every rule reads off one.

    One CTE, so the scope and its race subquery are applied once for the whole
    union, and the lifetime cutoff reaches every rule from here.
    """
    if lifetime:
        scope = [
            *scope,
            col(W3CLadderMatch.wc3_season) >= LIFETIME_FROM_W3C_SEASON,
        ]
    won, before, after = (
        col(W3CLadderMatch.won),
        col(W3CLadderMatch.mmr_before),
        col(W3CLadderMatch.mmr_after),
    )
    return (
        select(
            col(W3CLadderMatch.user_id).label("user_id"),
            col(W3CLadderMatch.id).label("id"),
            won.label("won"),
            col(W3CLadderMatch.start_time).label("start_time"),
            col(W3CLadderMatch.duration_s).label("duration_s"),
            col(W3CLadderMatch.map_name).label("map_name"),
            col(W3CLadderMatch.opp_race).label("opp_race"),
            func.lower(col(W3CLadderMatch.opp_battletag)).label("tag"),
            after.label("mmr_after"),
            _utc_day(col(W3CLadderMatch.start_time)).label("day"),
            case(
                (and_(before.is_not(None), after.is_not(None)), after - before),
                else_=literal(0),
            ).label("gain"),
            ladder.points_case(won, col(W3CLadderMatch.duration_s)).label("points"),
        )
        .where(*scope)
        .cte("scoped")
    )


def _utc_day(column: SQLColumnExpression[datetime]) -> ColumnElement[Any]:
    """The UTC day a match started on, as the instant it opened.

    An epoch is absolute, so the session time zone cannot move the day, which
    date() would let it do on Postgres.
    """
    epoch = extract("epoch", column)
    return epoch - epoch % 86400


def _member(query: Select[Any]) -> Select[Any]:
    """One member of the union. SQLite refuses a compound member that orders
    or limits, so every member is read from a subquery."""
    rows = query.subquery()
    return select(rows.c.user_id, rows.c.rule_id, rows.c.achieved_at, rows.c.extra)


def _ducks(rows: CTE, opponents: Mapping[int, frozenset[str]]) -> ColumnElement[bool]:
    """An opponent signed up on another team. Everyone on one team has the
    same opponents, so the clause carries one tag list per team."""
    teams: dict[frozenset[str], list[int]] = {}
    for user_id, tags in opponents.items():
        if tags:
            teams.setdefault(tags, []).append(user_id)
    return or_(
        false(),
        *(
            and_(rows.c.user_id.in_(user_ids), rows.c.tag.in_(tags))
            for tags, user_ids in teams.items()
        ),
    )


def _first_match(rows: CTE, won: bool, rule: str) -> Select[Any]:
    """The oldest match of the scope, when it went this way."""
    ranked = select(
        rows.c.user_id,
        rows.c.won,
        rows.c.start_time,
        func.row_number()
        .over(partition_by=rows.c.user_id, order_by=(rows.c.start_time, rows.c.id))
        .label("n"),
    ).subquery()
    return select(
        ranked.c.user_id,
        literal(rule).label("rule_id"),
        ranked.c.start_time.label("achieved_at"),
        literal(0).label("extra"),
    ).where(ranked.c.n == 1, ranked.c.won == won)


def _nth_result(rows: CTE, won: bool, n: int, rule: str) -> Select[Any]:
    """The match that made these n wins, or these n losses."""
    ranked = (
        select(
            rows.c.user_id,
            rows.c.start_time,
            func.row_number()
            .over(partition_by=rows.c.user_id, order_by=(rows.c.start_time, rows.c.id))
            .label("n"),
        )
        .where(rows.c.won == won)
        .subquery()
    )
    return select(
        ranked.c.user_id,
        literal(rule).label("rule_id"),
        ranked.c.start_time.label("achieved_at"),
        literal(0).label("extra"),
    ).where(ranked.c.n == n)


def _streak(rows: CTE, won: bool, n: int, rule: str) -> Select[Any]:
    """The match that completed the first run of n results the same way.

    Gaps and islands: a row's rank less its rank among the rows of its own
    result is constant over a run, so it names the run.
    """
    order = (rows.c.start_time, rows.c.id)
    runs = select(
        rows.c.user_id,
        rows.c.won,
        rows.c.id,
        rows.c.start_time,
        (
            func.row_number().over(partition_by=rows.c.user_id, order_by=order)
            - func.row_number().over(
                partition_by=(rows.c.user_id, rows.c.won), order_by=order
            )
        ).label("run"),
    ).subquery()
    ranked = (
        select(
            runs.c.user_id,
            runs.c.start_time,
            func.row_number()
            .over(
                partition_by=(runs.c.user_id, runs.c.run),
                order_by=(runs.c.start_time, runs.c.id),
            )
            .label("n"),
        )
        .where(runs.c.won == won)
        .subquery()
    )
    return (
        select(
            ranked.c.user_id,
            literal(rule).label("rule_id"),
            func.min(ranked.c.start_time).label("achieved_at"),
            literal(0).label("extra"),
        )
        .where(ranked.c.n == n)
        .group_by(ranked.c.user_id)
    )


def _mmr_reaches(rows: CTE, value: int, rule: str) -> Select[Any]:
    """The first match that left the player on this MMR exactly."""
    return (
        select(
            rows.c.user_id,
            literal(rule).label("rule_id"),
            func.min(rows.c.start_time).label("achieved_at"),
            literal(0).label("extra"),
        )
        .where(rows.c.mmr_after == value)
        .group_by(rows.c.user_id)
    )


def _tagged_win(
    rows: CTE, wanted: ColumnElement[bool], rule: str, extra: ColumnElement[Any]
) -> Select[Any]:
    """The first win over an opponent this clause names, and how many there
    were."""
    return (
        select(
            rows.c.user_id,
            literal(rule).label("rule_id"),
            func.min(rows.c.start_time).label("achieved_at"),
            extra.label("extra"),
        )
        .where(rows.c.won, wanted)
        .group_by(rows.c.user_id)
    )


def _by_race[T](column: ColumnElement[Any], values: Mapping[Race, T]) -> Case[T]:
    """One value per race. Each race binds as the member the column holds."""
    return case(*((column == race, literal(value)) for race, value in values.items()))


def _race_wins(rows: CTE, least: int) -> Select[Any]:
    """The win past `least` over the race the player beat most often.

    Every race counts in the comparison, Random included, and only the winner
    of it pays, so beating Random most pays nothing.
    """
    ranked = (
        select(
            rows.c.user_id,
            rows.c.opp_race,
            rows.c.start_time,
            func.row_number()
            .over(
                partition_by=(rows.c.user_id, rows.c.opp_race),
                order_by=(rows.c.start_time, rows.c.id),
            )
            .label("n"),
        )
        .where(rows.c.won, rows.c.opp_race.is_not(None))
        .subquery()
    )
    per_race = (
        select(
            ranked.c.user_id,
            ranked.c.opp_race,
            func.count().label("wins"),
            func.max(case((ranked.c.n == least + 1, ranked.c.start_time))).label(
                "achieved_at"
            ),
        )
        .group_by(ranked.c.user_id, ranked.c.opp_race)
        .subquery()
    )
    top = select(
        per_race.c.user_id,
        per_race.c.opp_race,
        per_race.c.wins,
        per_race.c.achieved_at,
        func.row_number()
        .over(
            partition_by=per_race.c.user_id,
            order_by=(
                per_race.c.wins.desc(),
                _by_race(per_race.c.opp_race, RACE_ORDER),
            ),
        )
        .label("rank"),
    ).subquery()
    return select(
        top.c.user_id,
        _by_race(top.c.opp_race, RACE_RULES).label("rule_id"),
        top.c.achieved_at.label("achieved_at"),
        top.c.wins.label("extra"),
    ).where(top.c.rank == 1, top.c.wins > least, top.c.opp_race.in_(RACE_RULES))


def _map_set(rows: CTE, maps: Sequence[str], rule: str) -> Select[Any]:
    """The win that completed the set: the first win on the last map left."""
    per_map = (
        select(
            rows.c.user_id,
            rows.c.map_name,
            func.min(rows.c.start_time).label("first"),
        )
        .where(rows.c.won, rows.c.map_name.in_(maps))
        .group_by(rows.c.user_id, rows.c.map_name)
        .subquery()
    )
    return (
        select(
            per_map.c.user_id,
            literal(rule).label("rule_id"),
            func.max(per_map.c.first).label("achieved_at"),
            literal(0).label("extra"),
        )
        .group_by(per_map.c.user_id)
        .having(func.count() == len(set(maps)))
    )


def _long_both(rows: CTE, seconds: int, rule: str) -> Select[Any]:
    """A win and a loss both longer than this, dated by the later of the
    two."""
    sides = (
        select(rows.c.user_id, rows.c.won, func.min(rows.c.start_time).label("first"))
        .where(rows.c.duration_s > seconds)
        .group_by(rows.c.user_id, rows.c.won)
        .subquery()
    )
    return (
        select(
            sides.c.user_id,
            literal(rule).label("rule_id"),
            func.max(sides.c.first).label("achieved_at"),
            literal(0).label("extra"),
        )
        .group_by(sides.c.user_id)
        .having(func.count() == 2)
    )


def _day_count(rows: CTE, n: int, rule: str) -> Select[Any]:
    """The nth match of the first UTC day that reached n matches."""
    ranked = select(
        rows.c.user_id,
        rows.c.start_time,
        func.row_number()
        .over(
            partition_by=(rows.c.user_id, rows.c.day),
            order_by=(rows.c.start_time, rows.c.id),
        )
        .label("n"),
    ).subquery()
    return (
        select(
            ranked.c.user_id,
            literal(rule).label("rule_id"),
            func.min(ranked.c.start_time).label("achieved_at"),
            literal(0).label("extra"),
        )
        .where(ranked.c.n == n)
        .group_by(ranked.c.user_id)
    )


def _day_mmr(rows: CTE, threshold: int, rule: str) -> Select[Any]:
    """The last match of the first UTC day the MMR moved past this on."""
    gain = func.sum(rows.c.gain)
    days = (
        select(rows.c.user_id, func.max(rows.c.start_time).label("last"))
        .group_by(rows.c.user_id, rows.c.day)
        .having(gain > threshold if threshold > 0 else gain < threshold)
        .subquery()
    )
    return select(
        days.c.user_id,
        literal(rule).label("rule_id"),
        func.min(days.c.last).label("achieved_at"),
        literal(0).label("extra"),
    ).group_by(days.c.user_id)


def _goal(rows: CTE, target: int, rule: str) -> Select[Any]:
    """The match the running ladder points reached the target on.

    The total decides and the rows only date it, so a total that reaches the
    target without a row that does falls back on the last match.
    """
    running = select(
        rows.c.user_id,
        rows.c.start_time,
        func.sum(rows.c.points)
        .over(partition_by=rows.c.user_id, order_by=(rows.c.start_time, rows.c.id))
        .label("run"),
        func.sum(rows.c.points).over(partition_by=rows.c.user_id).label("total"),
    ).subquery()
    return (
        select(
            running.c.user_id,
            literal(rule).label("rule_id"),
            func.coalesce(
                func.min(case((running.c.run >= target, running.c.start_time))),
                func.max(running.c.start_time),
            ).label("achieved_at"),
            literal(0).label("extra"),
        )
        .group_by(running.c.user_id)
        .having(func.max(running.c.total) >= target)
    )
