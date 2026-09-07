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
from dataclasses import dataclass, field, replace
from datetime import datetime
from math import ceil
from operator import itemgetter
from typing import Any

from sqlalchemy import (
    CTE,
    Case,
    ColumnElement,
    Integer,
    Row,
    Select,
    SQLColumnExpression,
    String,
    and_,
    case,
    cast,
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

from app.core import achievement_shapes as shape
from app.core import ladder
from app.core.achievements import (
    ADDICTED,
    ALWAYS_HERE,
    ANTI_RANDOM,
    BY_ID,
    CAPTAINS_DUTY,
    CIVIL_WAR,
    CLIMBER,
    COMEBACK,
    DATS_FAKT_AP,
    DOUBLE_UP,
    DUCK_HUNTING,
    EARLY_BIRD,
    ELITE,
    ELITE_MMR,
    FALLING_STAR,
    FIRST_TO_FIFTY,
    FIVE_A_DAY,
    FOUR_HORSEMEN,
    GAMES_25,
    GAMES_50,
    GAMES_100,
    GRAND_TOUR,
    HAT_TRICK,
    HOLD_THE_LINE,
    HOLIDAY,
    HOLIDAY_MAPS,
    HOME_TURF,
    HUNTING_SEASON,
    I_AM_THE_CAPTAIN_NOW,
    JOIN_THEM,
    LADDER_GOAL,
    LADDER_GOAL_REACHED,
    LADDER_MAPS,
    LAST_CALL,
    LONG_GAME_S,
    LOSE_FIRST,
    MAP_WIN,
    MARATHON,
    MIRROR_MASTER,
    MONTH_OF_SUNDAYS,
    NEMESIS,
    NEVER_GONE,
    NEW_MAPS,
    NEWBIE,
    OFF_DUTY,
    ONE_SITTING,
    OPEN_SEASON,
    PLUS_TWENTY,
    POWER_HOUR,
    RACE_ACHIEVEMENTS,
    RACE_IDS,
    RACE_TOUR,
    REPEAT_OFFENDER,
    REVENGE,
    RISING_STAR,
    RIVAL,
    SAD_TROMBONE,
    SLAYER_GAMES,
    SLAYER_RATE,
    SLAYERS,
    SPEEDRUNNER,
    STREAK_WEEK,
    TOURIST,
    TWENTY_DAYS,
    TWENTY_HOURS,
    WEEK_ONE,
    WEEKEND_WARRIOR,
    WEEKLY_REGULAR,
    WELCOME_BACK,
    WIDE_NET,
    WIN_EVERY_MAP,
    WIN_FIRST,
    WIN_POOL,
    WIN_STREAK,
    WIN_STREAK_2,
    WINNER_WINNER,
    WINTER,
    WINTER_MAPS,
    Achievement,
    PaidSet,
    per_map,
    priced_id,
)
from app.models.enums import Race
from app.models.w3c_ladder_match import W3CLadderMatch

# The rules that pay per match: what one adds to the price, and how it reads
VARIABLE = {
    DUCK_HUNTING.id: (5, " - {} kill(s)"),
    **{rule.id: (1, " - {} wins!") for rule in RACE_ACHIEVEMENTS.values()},
}

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


@dataclass(frozen=True)
class Context:
    """What the rules read beside the matches: the season around them.

    `teams` maps a team id to the players on it and `tags` to their battle
    tags in lower case; a player on no team is in neither. `league_race` is
    the race each player signed up on, the one the scope keeps. `window` is
    the season's, None over a lifetime; `pool` its map names. `lifetime` is
    the scope that spans seasons, which starts its rules at
    LIFETIME_FROM_W3C_SEASON.
    """

    window: tuple[datetime, datetime] | None = None
    pool: Sequence[str] = ()
    teams: Mapping[int, Sequence[int]] = field(default_factory=dict)
    tags: Mapping[int, Sequence[str]] = field(default_factory=dict)
    captains: frozenset[str] = frozenset()
    captain_ids: Sequence[int] = ()
    league_race: Mapping[int, str | None] = field(default_factory=dict)
    lifetime: bool = False
    # Per rule id, the numbers this scope's price rows override
    params: Mapping[str, Mapping[str, int]] = field(default_factory=dict)

    def n(self, rule: Achievement, key: str) -> int:
        """The number a rule reads: the scope's override, else the rule's default."""
        return self.params.get(rule.id, {}).get(key, rule.params[key])

    @property
    def opponents(self) -> dict[int, frozenset[str]]:
        """Per player, the tags of everyone on another team."""
        everyone = frozenset(tag for tags in self.tags.values() for tag in tags)
        return {
            user_id: everyone - frozenset(self.tags.get(team, ()))
            for team, users in self.teams.items()
            for user_id in users
        }

    @property
    def teammates(self) -> dict[int, frozenset[str]]:
        """Per player, the tags of everyone on his own team."""
        return {
            user_id: frozenset(self.tags.get(team, ()))
            for team, users in self.teams.items()
            for user_id in users
        }

    @property
    def members(self) -> frozenset[str]:
        return frozenset(tag for tags in self.tags.values() for tag in tags)

    @property
    def since_day(self) -> int:
        """The epoch of the window's first UTC day."""
        assert self.window is not None
        epoch = int(self.window[0].timestamp())
        return epoch - epoch % shape.DAY_S

    @property
    def until(self) -> int:
        assert self.window is not None
        return int(self.window[1].timestamp())

    @property
    def weeks(self) -> int:
        """The weeks the window spans, the last one however short."""
        assert self.window is not None
        return ceil(((self.window[1] - self.window[0]).days + 1) / 7)


def earned(
    session: OrmSession,
    scope: Sequence[ColumnElement[bool]],
    paid: PaidSet,
    ctx: Context,
    any_race: Sequence[ColumnElement[bool]] | None = None,
) -> dict[int, list[Achievement]]:
    """Every player's achievements over the scope, oldest first.

    `paid` is what this scope pays for each rule and a rule it does not name
    is not evaluated. `any_race` is the scope without the league race clause,
    which the two off-race rules read; None skips them.
    """
    rows = scoped(scope, ctx.lifetime)
    queries = _queries(rows, ctx)
    if any_race is not None:
        queries += _off_race_queries(scoped(any_race, ctx.lifetime, "any_race"), ctx)
    wanted = [(ids, query) for ids, query in queries if paid.keys() & set(ids)]
    if not wanted:
        return {}
    order = {rule_id: n for n, (ids, _) in enumerate(wanted) for rule_id in ids}
    rows = session.execute(union_all(*(_member(query) for _, query in wanted))).all()
    return _badges(rows, paid, order, ctx.params)


def _badges(
    rows: Iterable[Row[Any]],
    paid: PaidSet,
    order: Mapping[str, int],
    params: Mapping[str, Mapping[str, int]] = {},
) -> dict[int, list[Achievement]]:
    """The badges these rows read as, per player, oldest first.

    Two badges of one instant keep the order the rules are evaluated in.
    """
    found: dict[int, list[tuple[datetime, int, Achievement]]] = {}
    for row in rows:
        priced = priced_id(row.rule_id)
        price = paid.get(priced)
        if price is None:
            continue
        rate, suffix = VARIABLE.get(priced, (0, ""))
        rule = BY_ID[priced]
        if priced != row.rule_id:
            rule = per_map(row.rule_id.removeprefix(f"{MAP_WIN.id}:"))
        badge = replace(
            rule,
            points=price + rate * row.extra,
            description=rule.text(params.get(priced)) + suffix.format(row.extra),
            achieved_at=row.achieved_at,
        )
        found.setdefault(row.user_id, []).append(
            (row.achieved_at, order[priced], badge)
        )
    return {
        user_id: [badge for _, _, badge in sorted(items, key=itemgetter(0, 1))]
        for user_id, items in found.items()
    }


Query = tuple[tuple[str, ...], Select[Any]]


def _queries(rows: CTE, ctx: Context) -> list[Query]:
    """Every rule as one statement, in the order the rules are evaluated in.

    A rule whose inputs are empty is dropped: no roster means no duck and no
    captain to beat, no window means no first week.
    """
    opponents, captains, captain_ids = ctx.opponents, ctx.captains, ctx.captain_ids
    queries: list[Query] = [
        ((WIN_FIRST.id,), _first_match(rows, True, WIN_FIRST.id)),
        ((LOSE_FIRST.id,), _first_match(rows, False, LOSE_FIRST.id)),
        ((WINNER_WINNER.id,), _nth_result(rows, True, 100, WINNER_WINNER.id)),
        ((SAD_TROMBONE.id,), _nth_result(rows, False, 100, SAD_TROMBONE.id)),
        ((ELITE.id,), _mmr_reaches(rows, ELITE_MMR, ELITE.id)),
        ((DATS_FAKT_AP.id,), _streak(rows, False, 10, DATS_FAKT_AP.id)),
        (
            (WIN_STREAK.id,),
            _streak(rows, True, ctx.n(WIN_STREAK, "wins"), WIN_STREAK.id),
        ),
        (
            (WIN_STREAK_2.id,),
            _streak(rows, True, ctx.n(WIN_STREAK_2, "wins"), WIN_STREAK_2.id),
        ),
        (
            (HAT_TRICK.id,),
            _streak(rows, True, ctx.n(HAT_TRICK, "wins"), HAT_TRICK.id),
        ),
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
    return queries + _s19_queries(rows, ctx)


def _one(rule: Achievement, query: Select[Any]) -> Query:
    return ((rule.id,), query)


def _s19_queries(rows: CTE, ctx: Context) -> list[Query]:
    """The S19 rules, built from core.achievement_shapes."""
    won, tag = rows.c.won, rows.c.tag
    mirror = shape.all_of(
        rows.c.played_race.is_not(None), rows.c.played_race == rows.c.opp_played_race
    )
    queries = [
        _one(GAMES_25, shape.nth(rows, GAMES_25.id, ctx.n(GAMES_25, "games"))),
        _one(GAMES_50, shape.nth(rows, GAMES_50.id, ctx.n(GAMES_50, "games"))),
        _one(GAMES_100, shape.nth(rows, GAMES_100.id, ctx.n(GAMES_100, "games"))),
        _one(
            PLUS_TWENTY,
            shape.running(
                rows,
                PLUS_TWENTY.id,
                case((won, 1), else_=-1),
                ctx.n(PLUS_TWENTY, "wins"),
            ),
        ),
        _one(
            TWENTY_HOURS,
            shape.running(
                rows,
                TWENTY_HOURS.id,
                rows.c.duration_s,
                ctx.n(TWENTY_HOURS, "hours") * 3600,
            ),
        ),
        _one(
            STREAK_WEEK,
            shape.consecutive_periods(
                rows,
                STREAK_WEEK.id,
                shape.day_number(rows),
                1,
                ctx.n(STREAK_WEEK, "days"),
            ),
        ),
        _one(
            TWENTY_DAYS,
            shape.periods(
                rows, TWENTY_DAYS.id, rows.c.day, 1, ctx.n(TWENTY_DAYS, "days")
            ),
        ),
        _one(
            FIVE_A_DAY,
            shape.periods(
                rows,
                FIVE_A_DAY.id,
                rows.c.day,
                ctx.n(FIVE_A_DAY, "games"),
                ctx.n(FIVE_A_DAY, "days"),
            ),
        ),
        _one(
            WELCOME_BACK,
            shape.after_break(
                rows, WELCOME_BACK.id, ctx.n(WELCOME_BACK, "days") * shape.DAY_S
            ),
        ),
        _one(
            ONE_SITTING,
            shape.within(
                rows,
                ONE_SITTING.id,
                ctx.n(ONE_SITTING, "games"),
                ctx.n(ONE_SITTING, "hours") * 3600,
            ),
        ),
        _one(
            POWER_HOUR,
            shape.within(rows, POWER_HOUR.id, ctx.n(POWER_HOUR, "wins"), 3600, won),
        ),
        _one(
            WEEKEND_WARRIOR,
            shape.nth(
                rows,
                WEEKEND_WARRIOR.id,
                ctx.n(WEEKEND_WARRIOR, "games"),
                shape.weekend(rows),
            ),
        ),
        _one(
            REPEAT_OFFENDER,
            shape.streak_count(
                rows,
                REPEAT_OFFENDER.id,
                True,
                ctx.n(REPEAT_OFFENDER, "streak"),
                ctx.n(REPEAT_OFFENDER, "times"),
            ),
        ),
        _one(CLIMBER, shape.span(rows, CLIMBER.id, ctx.n(CLIMBER, "mmr"))),
        _one(
            HOLD_THE_LINE,
            shape.held_peak(
                rows,
                HOLD_THE_LINE.id,
                ctx.n(HOLD_THE_LINE, "mmr"),
                ctx.n(HOLD_THE_LINE, "games"),
            ),
        ),
        _one(
            COMEBACK,
            shape.from_low(
                rows, COMEBACK.id, ctx.n(COMEBACK, "mmr"), ctx.n(COMEBACK, "games")
            ),
        ),
        _one(
            HOME_TURF,
            shape.group_nth(
                rows, HOME_TURF.id, ctx.n(HOME_TURF, "wins"), (rows.c.map_name,), won
            ),
        ),
        _one(
            RACE_TOUR,
            shape.covers(rows, RACE_TOUR.id, rows.c.opp_race, list(RACE_RULES), won),
        ),
        _one(
            MIRROR_MASTER,
            shape.nth(
                rows, MIRROR_MASTER.id, ctx.n(MIRROR_MASTER, "wins"), won, mirror
            ),
        ),
        _one(
            ANTI_RANDOM,
            shape.nth(
                rows,
                ANTI_RANDOM.id,
                ctx.n(ANTI_RANDOM, "wins"),
                won,
                rows.c.opp_race == Race.RANDOM,
            ),
        ),
        (
            tuple(rule.id for rule in SLAYERS.values()),
            shape.rate_by(
                rows,
                {Race[code]: rule.id for code, rule in SLAYERS.items()},
                rows.c.opp_race,
                SLAYER_RATE,
                SLAYER_GAMES,
            ),
        ),
        _one(
            NEMESIS,
            shape.group_nth(
                rows, NEMESIS.id, ctx.n(NEMESIS, "wins"), (tag,), won, tag.is_not(None)
            ),
        ),
        _one(REVENGE, shape.revenge(rows, REVENGE.id, tag)),
        _one(
            RIVAL,
            shape.group_nth(
                rows, RIVAL.id, ctx.n(RIVAL, "games"), (tag,), tag.is_not(None)
            ),
        ),
        _one(
            WIDE_NET,
            shape.covers_count(
                rows, WIDE_NET.id, tag, ctx.n(WIDE_NET, "opponents"), won
            ),
        ),
        _one(
            SPEEDRUNNER,
            shape.first(
                rows,
                SPEEDRUNNER.id,
                won,
                rows.c.duration_s <= ctx.n(SPEEDRUNNER, "minutes") * 60,
            ),
        ),
        _one(
            MARATHON,
            shape.first(
                rows, MARATHON.id, rows.c.duration_s >= ctx.n(MARATHON, "minutes") * 60
            ),
        ),
        _one(
            FIRST_TO_FIFTY,
            shape.first_across(
                shape.nth(rows, FIRST_TO_FIFTY.id, ctx.n(FIRST_TO_FIFTY, "games"))
            ),
        ),
    ]
    if ctx.window is not None:
        day, week = (
            shape.day_index(rows, ctx.since_day),
            shape.week_index(rows, ctx.since_day),
        )
        last_days = ctx.until - ctx.n(LAST_CALL, "days") * shape.DAY_S
        queries += [
            _one(
                EARLY_BIRD,
                shape.first(rows, EARLY_BIRD.id, day < ctx.n(EARLY_BIRD, "days")),
            ),
            _one(
                WEEK_ONE,
                shape.nth(rows, WEEK_ONE.id, ctx.n(WEEK_ONE, "games"), day < 7),
            ),
            _one(LAST_CALL, shape.first(rows, LAST_CALL.id, rows.c.epoch > last_days)),
            _one(ALWAYS_HERE, shape.periods(rows, ALWAYS_HERE.id, week, 1, ctx.weeks)),
            _one(
                WEEKLY_REGULAR,
                shape.periods(
                    rows,
                    WEEKLY_REGULAR.id,
                    week,
                    ctx.n(WEEKLY_REGULAR, "games"),
                    ctx.n(WEEKLY_REGULAR, "weeks"),
                ),
            ),
            _one(
                MONTH_OF_SUNDAYS,
                shape.consecutive_periods(
                    rows,
                    MONTH_OF_SUNDAYS.id,
                    week,
                    1,
                    ctx.n(MONTH_OF_SUNDAYS, "weekends"),
                    shape.weekend(rows),
                ),
            ),
            _one(
                NEVER_GONE,
                shape.no_break(
                    rows,
                    NEVER_GONE.id,
                    ctx.n(NEVER_GONE, "days") * shape.DAY_S,
                    ctx.n(NEVER_GONE, "games"),
                    ctx.since_day,
                    ctx.until,
                ),
            ),
        ]
    if ctx.pool:
        queries += [
            _one(
                WIN_POOL,
                shape.covers(rows, WIN_POOL.id, rows.c.map_name, ctx.pool, won),
            ),
            _one(TOURIST, shape.covers(rows, TOURIST.id, rows.c.map_name, ctx.pool)),
        ]
        queries += [
            (
                (MAP_WIN.id,),
                shape.first(rows, per_map(name).id, won, rows.c.map_name == name),
            )
            for name in ctx.pool
        ]
    if ctx.members:
        member = tag.in_(sorted(ctx.members))
        queries += [
            _one(
                HUNTING_SEASON,
                shape.first(rows, HUNTING_SEASON.id, won, _ducks(rows, ctx.opponents)),
            ),
            _one(
                OPEN_SEASON,
                shape.covers_count(
                    rows,
                    OPEN_SEASON.id,
                    tag,
                    ctx.n(OPEN_SEASON, "players"),
                    won,
                    member,
                ),
            ),
            _one(
                CIVIL_WAR,
                shape.first(rows, CIVIL_WAR.id, won, _ducks(rows, ctx.teammates)),
            ),
        ]
    if len(ctx.tags) > 1:
        own = shape.team_of(rows, ctx.teams)
        other = shape.opponent_team(rows, ctx.tags)
        queries.append(
            _one(
                GRAND_TOUR,
                shape.covers(
                    rows,
                    GRAND_TOUR.id,
                    other,
                    list(ctx.tags),
                    won,
                    other != own,
                    need=len(ctx.tags) - 1,
                ),
            )
        )
    if ctx.captain_ids:
        queries.append(
            _one(
                CAPTAINS_DUTY,
                shape.nth(
                    rows,
                    CAPTAINS_DUTY.id,
                    ctx.n(CAPTAINS_DUTY, "games"),
                    rows.c.user_id.in_(list(ctx.captain_ids)),
                ),
            )
        )
    return queries


def _off_race_queries(rows: CTE, ctx: Context) -> list[Query]:
    """The two rules that read every race the player played, not only the
    league one."""
    # Both sides as text: Postgres will not compare its race enum with a CASE
    # of bound strings, and the enum stores the race code
    league = shape.lookup(
        [
            (rows.c.user_id == user_id, _code(race))
            for user_id, race in ctx.league_race.items()
            if race
        ],
        String,
    )
    return [
        _one(
            FOUR_HORSEMEN,
            shape.covers(
                rows, FOUR_HORSEMEN.id, rows.c.played_race, list(RACE_RULES), rows.c.won
            ),
        ),
        _one(
            OFF_DUTY,
            shape.first(
                rows, OFF_DUTY.id, rows.c.won, cast(rows.c.race, String) != league
            ),
        ),
    ]


def _code(race: Race | str) -> str:
    """The race as the enum stores it: its code, HU for Race.HU."""
    return race.value if isinstance(race, Race) else str(race)


def scoped(
    scope: Sequence[ColumnElement[bool]], lifetime: bool, name: str = "scoped"
) -> CTE:
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
            col(W3CLadderMatch.race).label("race"),
            col(W3CLadderMatch.played_race).label("played_race"),
            col(W3CLadderMatch.opp_race).label("opp_race"),
            col(W3CLadderMatch.opp_played_race).label("opp_played_race"),
            func.lower(col(W3CLadderMatch.opp_battletag)).label("tag"),
            col(W3CLadderMatch.w3c_match_id).label("match_id"),
            before.label("mmr_before"),
            after.label("mmr_after"),
            _epoch(col(W3CLadderMatch.start_time)).label("epoch"),
            _utc_day(col(W3CLadderMatch.start_time)).label("day"),
            case(
                (and_(before.is_not(None), after.is_not(None)), after - before),
                else_=literal(0),
            ).label("gain"),
            ladder.points_case(won, col(W3CLadderMatch.duration_s)).label("points"),
        )
        .where(*scope)
        .cte(name)
    )


def _epoch(column: SQLColumnExpression[datetime]) -> ColumnElement[Any]:
    """The instant as whole seconds, the unit the time windows count in."""
    return cast(func.floor(extract("epoch", column)), Integer)


def _utc_day(column: SQLColumnExpression[datetime]) -> ColumnElement[Any]:
    """The UTC day a match started on, as the instant it opened.

    An epoch is absolute, so the session time zone cannot move the day, which
    date() would let it do on Postgres.
    """
    epoch = _epoch(column)
    return epoch - epoch % 86400


def _member(query: Select[Any]) -> Select[Any]:
    """One member of the union. SQLite refuses a compound member that orders
    or limits, so every member is read from a subquery."""
    rows = query.subquery()
    return select(rows.c.user_id, rows.c.rule_id, rows.c.achieved_at, rows.c.extra)


def _ducks(rows: CTE, opponents: Mapping[int, frozenset[str]]) -> ColumnElement[bool]:
    """An opponent in the player's tag set. Everyone on one team has the same
    set, so the clause carries one tag list per team."""
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
