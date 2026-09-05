"""The team achievements: badges a season pays to a team, never a player.

Two ways to earn one. Five read the roster's matches in SQL, one union over
the scoped CTE of core.achievement_rules with the team in the partition. The
rest fold what the ladder answer already holds per player: totals, MMR
spans, days, races and the player badges. A fold reads no database.

A folded badge carries no date unless it folds dated badges, so most team
badges answer achieved_at None. ponytail: date them from SQL when a page
needs the order.
"""

from collections.abc import Callable, Mapping, Sequence
from dataclasses import replace
from datetime import date, datetime
from typing import Any

from sqlalchemy import (
    CTE,
    ColumnElement,
    CompoundSelect,
    Row,
    Select,
    func,
    literal,
    select,
    union_all,
)
from sqlalchemy.orm import Session as OrmSession

from app.core import achievement_shapes as shape
from app.core.achievement_rules import BY_ID, Context, scoped
from app.core.achievements import (
    BRAGGING_RIGHTS,
    BRAGGING_WINS,
    EVERY_WEEK,
    EVERYONE_HUNTS,
    EVERYONE_SCORES,
    FAST_START,
    FIFTY_FACES,
    FIFTY_FACES_N,
    FULL_ROSTER,
    HALF_REGULAR,
    HUNTING_SEASON,
    NEVER_BLANK,
    NOBODY_LEFT,
    ROSTER_GAMES,
    SPARRING_GAMES,
    SPARRING_PARTNERS,
    TEAM_CLIMB,
    TEAM_CLIMB_CAP,
    TEAM_CLIMB_TARGET,
    TEAM_GOAL,
    TEAM_GOAL_CAP,
    TEAM_GOAL_TARGET,
    TEAM_GRAND_TOUR,
    TEAM_MAP_COVERAGE,
    TEAM_NIGHT,
    TEAM_NIGHT_GAMES,
    TEAM_NIGHT_PLAYERS,
    TEAM_RACE_COVERAGE,
    TEAM_WEEK_GAMES,
    TEAM_WEEK_PLAYERS,
    TWO_HUNDRED,
    TWO_HUNDRED_CAP,
    TWO_HUNDRED_TARGET,
    WEEKLY_REGULAR,
    Achievement,
    PaidSet,
)
from app.models.enums import Race

RACES = frozenset(race.value for race in Race if race is not Race.RANDOM)


def earned(
    session: OrmSession,
    scope: Sequence[ColumnElement[bool]],
    ctx: Context,
    paid: PaidSet,
    totals: Mapping[int, Row],
    spans: Mapping[int, Row],
    days: Mapping[int, Sequence[Row]],
    races: Mapping[int, Mapping[Any, Sequence[int]]],
    players: Mapping[int, Sequence[Achievement]],
) -> dict[int, list[Achievement]]:
    """Every team's badges, keyed by team id. One statement, then the folds."""
    found: dict[int, list[Achievement]] = {}

    def pay(team: int, rule: Achievement, at: datetime | None) -> None:
        price = paid.get(rule.id)
        if price is not None:
            found.setdefault(team, []).append(
                replace(rule, points=price, achieved_at=at)
            )

    if ctx.teams and paid.keys() & SQL_RULES:
        rows = scoped(scope, ctx.lifetime)
        for row in session.execute(_statement(rows, ctx)).all():
            pay(row.team_id, BY_ID[row.rule_id], row.achieved_at)
    for team, users in ctx.teams.items():
        _fold(pay, team, list(users), ctx, totals, spans, days, races, players)
    return found


SQL_RULES = frozenset(
    rule.id
    for rule in (
        TEAM_MAP_COVERAGE,
        TEAM_GRAND_TOUR,
        FIFTY_FACES,
        BRAGGING_RIGHTS,
        SPARRING_PARTNERS,
    )
)


def _statement(rows: CTE, ctx: Context) -> CompoundSelect[Any]:
    """The five SQL team rules as one union of (team_id, rule_id, achieved_at)."""
    team = shape.team_of(rows, ctx.teams).label("team_id")
    opp_team = shape.opponent_team(rows, ctx.tags)
    won = rows.c.won
    members: list[Select[Any]] = []

    if ctx.pool:
        per_map = (
            select(
                team,
                rows.c.map_name.label("v"),
                func.min(rows.c.start_time).label("first"),
            )
            .where(won, rows.c.map_name.in_(list(ctx.pool)))
            .group_by(team, rows.c.map_name)
            .subquery()
        )
        members.append(
            select(
                per_map.c.team_id,
                literal(TEAM_MAP_COVERAGE.id).label("rule_id"),
                func.max(per_map.c.first).label("achieved_at"),
            )
            .group_by(per_map.c.team_id)
            .having(func.count() == len(set(ctx.pool)))
        )
    if len(ctx.tags) > 1:
        per_team = (
            select(
                team, opp_team.label("v"), func.min(rows.c.start_time).label("first")
            )
            .where(
                won, opp_team.is_not(None), opp_team != shape.team_of(rows, ctx.teams)
            )
            .group_by(team, opp_team)
            .subquery()
        )
        members.append(
            select(
                per_team.c.team_id,
                literal(TEAM_GRAND_TOUR.id).label("rule_id"),
                func.max(per_team.c.first).label("achieved_at"),
            )
            .group_by(per_team.c.team_id)
            .having(func.count() == len(ctx.tags) - 1)
        )
        beaten = (
            select(
                team,
                rows.c.start_time,
                func.row_number()
                .over(
                    partition_by=(team, opp_team),
                    order_by=(rows.c.start_time, rows.c.id),
                )
                .label("n"),
            )
            .where(
                won, opp_team.is_not(None), opp_team != shape.team_of(rows, ctx.teams)
            )
            .subquery()
        )
        members.append(
            select(
                beaten.c.team_id,
                literal(BRAGGING_RIGHTS.id).label("rule_id"),
                func.min(beaten.c.start_time).label("achieved_at"),
            )
            .where(beaten.c.n == BRAGGING_WINS)
            .group_by(beaten.c.team_id)
        )
    faces = (
        select(team, rows.c.tag.label("v"), func.min(rows.c.start_time).label("first"))
        .where(won, rows.c.tag.is_not(None))
        .group_by(team, rows.c.tag)
        .subquery()
    )
    ranked = select(
        faces.c.team_id,
        faces.c.first,
        func.row_number()
        .over(partition_by=faces.c.team_id, order_by=(faces.c.first, faces.c.v))
        .label("n"),
    ).subquery()
    members.append(
        select(
            ranked.c.team_id,
            literal(FIFTY_FACES.id).label("rule_id"),
            ranked.c.first.label("achieved_at"),
        ).where(ranked.c.n == FIFTY_FACES_N)
    )
    sparring = (
        select(
            team, rows.c.match_id.label("v"), func.min(rows.c.start_time).label("first")
        )
        .where(opp_team == shape.team_of(rows, ctx.teams))
        .group_by(team, rows.c.match_id)
        .subquery()
    )
    ranked_sparring = select(
        sparring.c.team_id,
        sparring.c.first,
        func.row_number()
        .over(
            partition_by=sparring.c.team_id, order_by=(sparring.c.first, sparring.c.v)
        )
        .label("n"),
    ).subquery()
    members.append(
        select(
            ranked_sparring.c.team_id,
            literal(SPARRING_PARTNERS.id).label("rule_id"),
            ranked_sparring.c.first.label("achieved_at"),
        ).where(ranked_sparring.c.n == SPARRING_GAMES)
    )
    # SQLite refuses a compound member that orders or limits, so each is a subquery
    return union_all(*(select(m.subquery()) for m in members))


def _fold(
    pay: Callable[[int, Achievement, datetime | None], None],
    team: int,
    users: list[int],
    ctx: Context,
    totals: Mapping[int, Any],
    spans: Mapping[int, Any],
    days: Mapping[int, Sequence[Any]],
    races: Mapping[int, Mapping[Any, Sequence[int]]],
    players: Mapping[int, Sequence[Achievement]],
) -> None:
    """The team badges that fold per-player numbers the answer already holds."""
    if not users:
        return

    def games(user: int) -> int:
        total = totals.get(user)
        return int(total.games or 0) if total is not None else 0

    def wins(user: int) -> int:
        total = totals.get(user)
        return int(total.wins or 0) if total is not None else 0

    def points(user: int) -> int:
        total = totals.get(user)
        return int(total.points or 0) if total is not None else 0

    def gain(user: int) -> int:
        span = spans.get(user)
        if span is None or span.start is None or span.current is None:
            return 0
        return int(span.current - span.start)

    def badge(user: int, rule: Achievement) -> Achievement | None:
        return next((b for b in players.get(user, ()) if b.id == rule.id), None)

    def dated(badges: list[Achievement], need: int) -> datetime | None:
        """When the `need`th of these badges was earned, None short of it."""
        dates = sorted(b.achieved_at for b in badges if b.achieved_at is not None)
        return dates[need - 1] if len(dates) >= need else None

    if all(games(u) >= ROSTER_GAMES for u in users):
        pay(team, FULL_ROSTER, None)
    if all(wins(u) >= 1 for u in users):
        pay(team, EVERYONE_SCORES, None)
    regulars = [b for u in users if (b := badge(u, WEEKLY_REGULAR)) is not None]
    if len(regulars) * 2 >= len(users):
        pay(team, HALF_REGULAR, dated(regulars, (len(users) + 1) // 2))
    hunters = [b for u in users if (b := badge(u, HUNTING_SEASON)) is not None]
    if len(hunters) == len(users):
        pay(team, EVERYONE_HUNTS, dated(hunters, len(users)))
    if sum(min(points(u), TEAM_GOAL_CAP) for u in users) >= TEAM_GOAL_TARGET:
        pay(team, TEAM_GOAL, None)
    if sum(min(games(u), TWO_HUNDRED_CAP) for u in users) >= TWO_HUNDRED_TARGET:
        pay(team, TWO_HUNDRED, None)
    if sum(min(gain(u), TEAM_CLIMB_CAP) for u in users) >= TEAM_CLIMB_TARGET:
        pay(team, TEAM_CLIMB, None)
    beaten: set[str] = set()
    for u in users:
        for race, record in races.get(u, {}).items():
            if record and record[0] > 0:
                beaten.add(getattr(race, "value", race))
    if RACES <= beaten:
        pay(team, TEAM_RACE_COVERAGE, None)

    if ctx.window is None:
        return
    start, end = ctx.window[0].date(), ctx.window[1].date()
    weeks = ctx.weeks

    def week_of(day: object) -> int:
        return (_date(day) - start).days // 7

    per_week: dict[int, dict[int, list[int]]] = {}  # week -> user -> [games, wins]
    per_day: dict[Any, dict[int, int]] = {}  # day -> user -> games
    for u in users:
        for row in days.get(u, ()):
            played = int((row.wins or 0) + (row.losses or 0))
            week = per_week.setdefault(week_of(row.day), {})
            record = week.setdefault(u, [0, 0])
            record[0] += played
            record[1] += int(row.wins or 0)
            per_day.setdefault(_date(row.day), {})[u] = played
    if all(
        sum(1 for r in per_week.get(w, {}).values() if r[0] >= TEAM_WEEK_GAMES)
        >= TEAM_WEEK_PLAYERS
        for w in range(weeks)
    ):
        pay(team, EVERY_WEEK, None)
    if all(any(r[1] > 0 for r in per_week.get(w, {}).values()) for w in range(weeks)):
        pay(team, NEVER_BLANK, None)
    if all(u in per_week.get(0, {}) for u in users):
        pay(team, FAST_START, None)
    last_week = {
        u for day, by_user in per_day.items() if (end - day).days < 7 for u in by_user
    }
    if all(u in last_week for u in users):
        pay(team, NOBODY_LEFT, None)
    if any(
        sum(by_user.values()) >= TEAM_NIGHT_GAMES and len(by_user) >= TEAM_NIGHT_PLAYERS
        for by_user in per_day.values()
    ):
        pay(team, TEAM_NIGHT, None)


def _date(value: object) -> date:
    """A day as a date; SQLite answers the date() function as text."""
    if isinstance(value, str):
        return date.fromisoformat(value[:10])
    if isinstance(value, datetime):
        return value.date()
    assert isinstance(value, date)
    return value
