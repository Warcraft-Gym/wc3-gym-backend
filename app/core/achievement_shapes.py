"""The query shapes the achievement rules are built from.

Every shape is one select of (user_id, rule_id, achieved_at, extra) over the
scoped CTE of core.achievement_rules, so the union there stays one statement
whatever the number of rules. A shape takes the rule id it answers and the
where clauses that narrow the matches; the rule module supplies both.

Ties between two matches of one instant break on the row id, as the ladder
sorts do, so a badge dates the same match on SQLite and Postgres.
"""

from collections.abc import Mapping, Sequence
from typing import Any

from sqlalchemy import (
    CTE,
    ColumnElement,
    Integer,
    Select,
    and_,
    case,
    cast,
    func,
    literal,
    select,
)
from sqlalchemy.sql import Subquery
from sqlalchemy.types import TypeEngine

DAY_S = 86400
WEEK_S = 7 * DAY_S


def _order(rows: CTE) -> tuple[ColumnElement[Any], ...]:
    return (rows.c.start_time, rows.c.id)


def _badge(
    user_id: ColumnElement[Any],
    rule: str | ColumnElement[Any],
    achieved_at: ColumnElement[Any],
    extra: ColumnElement[Any] | None = None,
) -> Select[Any]:
    return select(
        user_id.label("user_id"),
        (literal(rule) if isinstance(rule, str) else rule).label("rule_id"),
        achieved_at.label("achieved_at"),
        (literal(0) if extra is None else extra).label("extra"),
    )


def day_index(rows: CTE, since_day: int) -> ColumnElement[int]:
    """Days from the window's first day: 0 on that day."""
    return cast(func.floor((rows.c.day - since_day) / DAY_S), Integer)


def week_index(rows: CTE, since_day: int) -> ColumnElement[int]:
    """Weeks from the window's first day: 0 in the first seven days."""
    return cast(func.floor((rows.c.day - since_day) / WEEK_S), Integer)


def day_number(rows: CTE) -> ColumnElement[int]:
    """The UTC day as a count of days, so consecutive days differ by one."""
    return cast(func.floor(rows.c.day / DAY_S), Integer)


def weekday(rows: CTE) -> ColumnElement[int]:
    """The UTC weekday of the match, 0 on Sunday, from the day epoch."""
    return cast(func.floor(rows.c.day / DAY_S) + 4, Integer) % 7


def weekend(rows: CTE) -> ColumnElement[bool]:
    return weekday(rows).in_((0, 6))


def first(rows: CTE, rule: str, *where: ColumnElement[bool]) -> Select[Any]:
    """The oldest match these clauses keep."""
    return (
        _badge(rows.c.user_id, rule, func.min(rows.c.start_time))
        .where(*where)
        .group_by(rows.c.user_id)
    )


def nth(rows: CTE, rule: str, n: int, *where: ColumnElement[bool]) -> Select[Any]:
    """The nth match these clauses keep, oldest first."""
    ranked = (
        select(
            rows.c.user_id,
            rows.c.start_time,
            func.row_number()
            .over(partition_by=rows.c.user_id, order_by=_order(rows))
            .label("n"),
        )
        .where(*where)
        .subquery()
    )
    return _badge(ranked.c.user_id, rule, ranked.c.start_time).where(ranked.c.n == n)


def group_nth(
    rows: CTE,
    rule: str,
    n: int,
    keys: Sequence[ColumnElement[Any]],
    *where: ColumnElement[bool],
) -> Select[Any]:
    """The first group of the keys to collect n matches, dated by its nth."""
    ranked = (
        select(
            rows.c.user_id,
            rows.c.start_time,
            func.row_number()
            .over(partition_by=(rows.c.user_id, *keys), order_by=_order(rows))
            .label("n"),
        )
        .where(*where)
        .subquery()
    )
    return (
        _badge(ranked.c.user_id, rule, func.min(ranked.c.start_time))
        .where(ranked.c.n == n)
        .group_by(ranked.c.user_id)
    )


def covers(
    rows: CTE,
    rule: str,
    key: ColumnElement[Any],
    values: Sequence[Any],
    *where: ColumnElement[bool],
    need: int | None = None,
) -> Select[Any]:
    """`need` values of the key seen, every one by default, dated by the
    first match on the last one."""
    wanted = list(dict.fromkeys(values))
    need = len(wanted) if need is None else need
    per_value = (
        select(
            rows.c.user_id, key.label("v"), func.min(rows.c.start_time).label("first")
        )
        .where(*where, key.in_(wanted))
        .group_by(rows.c.user_id, key)
        .subquery()
    )
    return (
        _badge(per_value.c.user_id, rule, func.max(per_value.c.first))
        .group_by(per_value.c.user_id)
        .having(func.count() == need)
    )


def covers_count(
    rows: CTE, rule: str, key: ColumnElement[Any], n: int, *where: ColumnElement[bool]
) -> Select[Any]:
    """n distinct values of the key, dated by the first match on the nth."""
    per_value = (
        select(
            rows.c.user_id, key.label("v"), func.min(rows.c.start_time).label("first")
        )
        .where(*where, key.is_not(None))
        .group_by(rows.c.user_id, key)
        .subquery()
    )
    ranked = select(
        per_value.c.user_id,
        per_value.c.first,
        func.row_number()
        .over(
            partition_by=per_value.c.user_id,
            order_by=(per_value.c.first, per_value.c.v),
        )
        .label("n"),
    ).subquery()
    return _badge(ranked.c.user_id, rule, ranked.c.first).where(ranked.c.n == n)


def _runs(rows: CTE, won: bool) -> Subquery:
    """Every match of a run of this result, numbered inside its run.

    Gaps and islands: a row's rank less its rank among the rows of its own
    result is constant over a run, so it names the run.
    """
    order = _order(rows)
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
    return (
        select(
            runs.c.user_id,
            runs.c.start_time,
            runs.c.id,
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


def streak(rows: CTE, rule: str, won: bool, n: int) -> Select[Any]:
    """The match that completed the first run of n results the same way."""
    ranked = _runs(rows, won)
    return (
        _badge(ranked.c.user_id, rule, func.min(ranked.c.start_time))
        .where(ranked.c.n == n)
        .group_by(ranked.c.user_id)
    )


def streak_count(rows: CTE, rule: str, won: bool, n: int, times: int) -> Select[Any]:
    """The match that completed the `times`th separate run of n."""
    ranked = _runs(rows, won)
    completed = (
        select(
            ranked.c.user_id,
            ranked.c.start_time,
            func.row_number()
            .over(
                partition_by=ranked.c.user_id,
                order_by=(ranked.c.start_time, ranked.c.id),
            )
            .label("k"),
        )
        .where(ranked.c.n == n)
        .subquery()
    )
    return _badge(completed.c.user_id, rule, completed.c.start_time).where(
        completed.c.k == times
    )


def running(
    rows: CTE,
    rule: str,
    term: ColumnElement[Any],
    target: int,
    *where: ColumnElement[bool],
) -> Select[Any]:
    """The match a running sum of the term reached the target on."""
    summed = (
        select(
            rows.c.user_id,
            rows.c.start_time,
            func.sum(term)
            .over(partition_by=rows.c.user_id, order_by=_order(rows))
            .label("run"),
        )
        .where(*where)
        .subquery()
    )
    return (
        _badge(summed.c.user_id, rule, func.min(summed.c.start_time))
        .where(summed.c.run >= target)
        .group_by(summed.c.user_id)
    )


def _qualified(
    rows: CTE, period: ColumnElement[Any], min_games: int, *where: ColumnElement[bool]
) -> Subquery:
    """Every period with min_games matches, as the match that made it so."""
    ranked = (
        select(
            rows.c.user_id,
            period.label("p"),
            rows.c.start_time,
            rows.c.id,
            func.row_number()
            .over(partition_by=(rows.c.user_id, period), order_by=_order(rows))
            .label("n"),
        )
        .where(*where)
        .subquery()
    )
    return (
        select(ranked.c.user_id, ranked.c.p, ranked.c.start_time, ranked.c.id)
        .where(ranked.c.n == min_games)
        .subquery()
    )


def periods(
    rows: CTE,
    rule: str,
    period: ColumnElement[Any],
    min_games: int,
    count: int,
    *where: ColumnElement[bool],
) -> Select[Any]:
    """`count` periods of min_games matches, dated by the match that made the
    last of them."""
    qualified = _qualified(rows, period, min_games, *where)
    ranked = select(
        qualified.c.user_id,
        qualified.c.start_time,
        func.row_number()
        .over(
            partition_by=qualified.c.user_id,
            order_by=(qualified.c.start_time, qualified.c.id),
        )
        .label("k"),
    ).subquery()
    return _badge(ranked.c.user_id, rule, ranked.c.start_time).where(
        ranked.c.k == count
    )


def consecutive_periods(
    rows: CTE,
    rule: str,
    period: ColumnElement[Any],
    min_games: int,
    count: int,
    *where: ColumnElement[bool],
) -> Select[Any]:
    """`count` periods in a row, each of min_games matches, dated by the match
    that made the last of the first such run."""
    qualified = _qualified(rows, period, min_games, *where)
    islands = select(
        qualified.c.user_id,
        qualified.c.p,
        qualified.c.start_time,
        (
            qualified.c.p
            - func.row_number().over(
                partition_by=qualified.c.user_id, order_by=qualified.c.p
            )
        ).label("island"),
    ).subquery()
    ranked = select(
        islands.c.user_id,
        islands.c.start_time,
        func.row_number()
        .over(partition_by=(islands.c.user_id, islands.c.island), order_by=islands.c.p)
        .label("k"),
    ).subquery()
    return (
        _badge(ranked.c.user_id, rule, func.min(ranked.c.start_time))
        .where(ranked.c.k == count)
        .group_by(ranked.c.user_id)
    )


def within(
    rows: CTE, rule: str, n: int, seconds: int, *where: ColumnElement[bool]
) -> Select[Any]:
    """n matches inside one window of this many seconds, dated by the first
    match that has n-1 others in the window before it."""
    counted = (
        select(
            rows.c.user_id,
            rows.c.start_time,
            func.count()
            .over(
                partition_by=rows.c.user_id,
                order_by=rows.c.epoch,
                range_=(-seconds, 0),
            )
            .label("c"),
        )
        .where(*where)
        .subquery()
    )
    return (
        _badge(counted.c.user_id, rule, func.min(counted.c.start_time))
        .where(counted.c.c >= n)
        .group_by(counted.c.user_id)
    )


def _gaps(rows: CTE) -> Subquery:
    """Every match with the seconds since the player's previous one."""
    return select(
        rows.c.user_id,
        rows.c.start_time,
        rows.c.epoch,
        (
            rows.c.epoch
            - func.lag(rows.c.epoch).over(
                partition_by=rows.c.user_id, order_by=_order(rows)
            )
        ).label("gap"),
    ).subquery()


def after_break(rows: CTE, rule: str, seconds: int) -> Select[Any]:
    """The first match after a break of at least this many seconds."""
    gaps = _gaps(rows)
    return (
        _badge(gaps.c.user_id, rule, func.min(gaps.c.start_time))
        .where(gaps.c.gap >= seconds)
        .group_by(gaps.c.user_id)
    )


def no_break(
    rows: CTE,
    rule: str,
    seconds: int,
    min_games: int,
    since: int,
    until: int,
) -> Select[Any]:
    """Never a break of this many seconds, from within one of the window's
    start to within one of its end, over min_games matches. Dated by the last
    match, so it settles when the season does."""
    gaps = _gaps(rows)
    return (
        _badge(gaps.c.user_id, rule, func.max(gaps.c.start_time))
        .group_by(gaps.c.user_id)
        .having(
            func.count() >= min_games,
            func.coalesce(func.max(gaps.c.gap), 0) <= seconds,
            func.min(gaps.c.epoch) <= since + seconds,
            func.max(gaps.c.epoch) >= until - seconds,
        )
    )


def _rated(rows: CTE) -> Subquery:
    """The matches with an MMR at both ends, numbered from both ends."""
    return (
        select(
            rows.c.user_id,
            rows.c.start_time,
            rows.c.mmr_before,
            rows.c.mmr_after,
            func.row_number()
            .over(partition_by=rows.c.user_id, order_by=_order(rows))
            .label("n"),
            func.row_number()
            .over(
                partition_by=rows.c.user_id,
                order_by=(rows.c.start_time.desc(), rows.c.id.desc()),
            )
            .label("n_desc"),
        )
        .where(rows.c.mmr_before.is_not(None), rows.c.mmr_after.is_not(None))
        .subquery()
    )


def span(rows: CTE, rule: str, min_gain: int) -> Select[Any]:
    """MMR after the last rated match less MMR before the first, at least
    min_gain. Dated by the last rated match, so it settles with the season."""
    rated = _rated(rows)
    last = func.max(case((rated.c.n_desc == 1, rated.c.mmr_after)))
    start = func.max(case((rated.c.n == 1, rated.c.mmr_before)))
    return (
        _badge(rated.c.user_id, rule, func.max(rated.c.start_time))
        .group_by(rated.c.user_id)
        .having(last - start >= min_gain)
    )


def held_peak(rows: CTE, rule: str, within_mmr: int, min_games: int) -> Select[Any]:
    """min_games rated matches and a finish within this much of the season
    high. Dated by the last rated match."""
    rated = _rated(rows)
    last = func.max(case((rated.c.n_desc == 1, rated.c.mmr_after)))
    return (
        _badge(rated.c.user_id, rule, func.max(rated.c.start_time))
        .group_by(rated.c.user_id)
        .having(
            func.count() >= min_games,
            func.max(rated.c.mmr_after) - last <= within_mmr,
        )
    )


def from_low(rows: CTE, rule: str, min_gain: int, min_games: int) -> Select[Any]:
    """min_games rated matches and a finish at least min_gain above the
    season low. Dated by the last rated match."""
    rated = _rated(rows)
    last = func.max(case((rated.c.n_desc == 1, rated.c.mmr_after)))
    return (
        _badge(rated.c.user_id, rule, func.max(rated.c.start_time))
        .group_by(rated.c.user_id)
        .having(
            func.count() >= min_games,
            last - func.min(rated.c.mmr_after) >= min_gain,
        )
    )


def revenge(rows: CTE, rule: str, tag: ColumnElement[Any]) -> Select[Any]:
    """The first win over an opponent this player had lost to before."""
    losses = (
        select(
            rows.c.user_id,
            rows.c.start_time,
            rows.c.won,
            func.sum(case((rows.c.won, 0), else_=1))
            .over(
                partition_by=(rows.c.user_id, tag),
                order_by=_order(rows),
                rows=(None, -1),
            )
            .label("before"),
        )
        .where(tag.is_not(None))
        .subquery()
    )
    return (
        _badge(losses.c.user_id, rule, func.min(losses.c.start_time))
        .where(losses.c.won, losses.c.before > 0)
        .group_by(losses.c.user_id)
    )


def rate_by(
    rows: CTE,
    rules: dict[Any, str],
    key: ColumnElement[Any],
    rate: float,
    min_games: int,
) -> Select[Any]:
    """One badge per key value with min_games matches won at this rate. The
    rule id is the one the value maps to. Dated by the last such match."""
    won = func.sum(case((rows.c.won, 1), else_=0))
    per_key = (
        select(
            rows.c.user_id,
            key.label("v"),
            func.max(rows.c.start_time).label("last"),
        )
        .where(key.in_(list(rules)))
        .group_by(rows.c.user_id, key)
        .having(func.count() >= min_games, won * 100 >= func.count() * int(rate * 100))
        .subquery()
    )
    rule_id = case(
        *((per_key.c.v == value, literal(rule)) for value, rule in rules.items())
    )
    return _badge(per_key.c.user_id, rule_id, per_key.c.last)


def first_across(query: Select[Any]) -> Select[Any]:
    """The one player who earned the badge first, over the whole scope."""
    found = query.subquery()
    ranked = select(
        found.c.user_id,
        found.c.rule_id,
        found.c.achieved_at,
        found.c.extra,
        func.row_number()
        .over(order_by=(found.c.achieved_at, found.c.user_id))
        .label("k"),
    ).subquery()
    return select(
        ranked.c.user_id, ranked.c.rule_id, ranked.c.achieved_at, ranked.c.extra
    ).where(ranked.c.k == 1)


def lookup(
    whens: Sequence[tuple[ColumnElement[bool], object]],
    type_: TypeEngine[Any] | type[TypeEngine[Any]] | None = None,
) -> ColumnElement[Any]:
    """A CASE over these branches, NULL when there is none: SQLite refuses a
    CASE with only an ELSE."""
    if not whens:
        return literal(None, type_)
    return case(
        *((test, literal(value, type_)) for test, value in whens),
        else_=literal(None, type_),
    )


def team_of(rows: CTE, members: Mapping[int, Sequence[int]]) -> ColumnElement[Any]:
    """The team a match's player is on, from the roster passed as literals."""
    return lookup(
        [
            (rows.c.user_id.in_(list(users)), team)
            for team, users in members.items()
            if users
        ],
        Integer,
    )


def opponent_team(rows: CTE, tags: Mapping[int, Sequence[str]]) -> ColumnElement[Any]:
    """The team a match's opponent is on, from the roster tags, else NULL."""
    return lookup(
        [
            (rows.c.tag.in_(list(team_tags)), team)
            for team, team_tags in tags.items()
            if team_tags
        ],
        Integer,
    )


def all_of(*where: ColumnElement[bool]) -> ColumnElement[bool]:
    return and_(*where)
