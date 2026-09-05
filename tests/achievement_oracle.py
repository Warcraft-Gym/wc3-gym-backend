"""The achievement rules in Python, the oracle the SQL is proved against.

This was app/core/achievements.earned: the rule set read out of the wc3.no
bundle, evaluated over one player's ordered matches. The application answers
the badges from core.achievement_rules in SQL now, so the two are compared
over random match sequences in tests/test_achievement_parity.py.
"""

from collections import defaultdict
from collections.abc import Callable, Iterable, Sequence
from dataclasses import dataclass, field, replace
from datetime import date, datetime
from itertools import accumulate, pairwise
from math import ceil
from operator import itemgetter
from typing import Protocol

from app.core import ladder
from app.core.achievements import (
    ADDICTED,
    ALWAYS_HERE,
    ANTI_RANDOM,
    AWAY_DAYS,
    BUSY_DAY_GAMES,
    BUSY_DAYS,
    CAPTAIN_GAMES,
    CAPTAINS_DUTY,
    CIVIL_WAR,
    CLIMB,
    CLIMBER,
    DATS_FAKT_AP,
    DISTINCT_DAYS,
    DOUBLE_UP,
    DUCK_HUNTING,
    EARLY_BIRD,
    EARLY_DAYS,
    ELITE,
    ELITE_MMR,
    FALLING_STAR,
    FIRST_TO_FIFTY,
    FIVE_A_DAY,
    FOUR_HORSEMEN,
    GAMES_25,
    GAMES_50,
    GAMES_100,
    GAMES_TIERS,
    GONE_DAYS,
    GONE_GAMES,
    GRAND_TOUR,
    HOLD_GAMES,
    HOLD_THE_LINE,
    HOLD_WITHIN,
    HOLIDAY,
    HOLIDAY_MAPS,
    HOME_TURF,
    HOME_WINS,
    HOUR_WINS,
    HUNTING_SEASON,
    I_AM_THE_CAPTAIN_NOW,
    JOIN_THEM,
    LADDER_GOAL,
    LADDER_GOAL_REACHED,
    LADDER_MAPS,
    LADDER_SECONDS,
    LAST_CALL,
    LAST_DAYS,
    LONG_GAME_S,
    LOSE_FIRST,
    MARATHON,
    MARATHON_S,
    MIRROR_MASTER,
    MIRROR_WINS,
    MONTH_OF_SUNDAYS,
    NEMESIS,
    NEMESIS_WINS,
    NET_WINS,
    NEVER_GONE,
    NEW_MAPS,
    NEWBIE,
    OFF_DUTY,
    ONE_SITTING,
    OPEN_SEASON,
    OPEN_SEASON_N,
    PLUS_TWENTY,
    POWER_HOUR,
    RACE_ACHIEVEMENTS,
    RACE_IDS,
    RACE_TOUR,
    RANDOM_WINS,
    REPEAT_OFFENDER,
    REPEAT_STREAK,
    REPEAT_TIMES,
    RISING_STAR,
    RIVAL,
    RIVAL_GAMES,
    SAD_TROMBONE,
    SITTING_GAMES,
    SITTING_S,
    SLAYER_GAMES,
    SLAYER_RATE,
    SLAYERS,
    SPEEDRUN_S,
    SPEEDRUNNER,
    STREAK_DAYS,
    STREAK_WEEK,
    TOURIST,
    TWENTY_DAYS,
    TWENTY_HOURS,
    WEEK_ONE,
    WEEK_ONE_GAMES,
    WEEKEND_GAMES,
    WEEKEND_WARRIOR,
    WEEKEND_WEEKS,
    WEEKLY_GAMES,
    WEEKLY_REGULAR,
    WEEKLY_WEEKS,
    WELCOME_BACK,
    WIDE_NET,
    WIDE_NET_N,
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
)


class RaceValue(Protocol):
    """A race the way the models spell it, for example Race.NE."""

    @property
    def value(self) -> str: ...


class AchievementRow(Protocol):
    """What the rules read off a match, stored or straight from w3champions."""

    @property
    def won(self) -> bool: ...
    @property
    def start_time(self) -> datetime: ...
    @property
    def duration_s(self) -> int: ...
    @property
    def map_name(self) -> str | None: ...
    @property
    def race(self) -> RaceValue | None: ...
    @property
    def played_race(self) -> RaceValue | None: ...
    @property
    def opp_race(self) -> RaceValue | None: ...
    @property
    def opp_played_race(self) -> RaceValue | None: ...
    @property
    def opp_battletag(self) -> str | None: ...
    @property
    def mmr_before(self) -> int | None: ...
    @property
    def mmr_after(self) -> int | None: ...


def run_end(
    rows: Sequence[AchievementRow], want: bool, length: int
) -> AchievementRow | None:
    """The match that first completes a run of `length` results of `want`."""
    run = 0
    for row in rows:
        run = run + 1 if bool(row.won) == want else 0
        if run == length:
            return row
    return None


def by_day(rows: Iterable[AchievementRow]) -> dict[date, list[AchievementRow]]:
    """The matches of one player, grouped by the UTC day they started on."""
    days: dict[date, list[AchievementRow]] = defaultdict(list)
    for row in rows:
        days[row.start_time.date()].append(row)
    return days


def mmr_gain(row: AchievementRow) -> int:
    """What one match moved the player's MMR by, 0 when either end is missing."""
    if row.mmr_before is None or row.mmr_after is None:
        return 0
    return row.mmr_after - row.mmr_before


def top_race(wins: Sequence[AchievementRow]) -> tuple[str, int] | None:
    """The race the player won most against, and how often."""
    counts: dict[str, int] = defaultdict(int)
    for row in wins:
        if row.opp_race is not None:
            counts[row.opp_race.value] += 1
    if not counts:
        return None
    best = max(counts, key=lambda race: (counts[race], -RACE_IDS[race]))
    return best, counts[best]


def completes(
    wins: Sequence[AchievementRow], maps: Sequence[str]
) -> AchievementRow | None:
    """The win that completed the set of maps, None while one is still open."""
    left = set(maps)
    for row in wins:
        left.discard(row.map_name)
        if not left:
            return row
    return None


def nth(rows: Sequence[AchievementRow], count: int) -> AchievementRow | None:
    """The match that made these `count` many, None short of it."""
    return rows[count - 1] if len(rows) >= count else None


def first(rows: Iterable[AchievementRow]) -> AchievementRow | None:
    """The oldest of these matches, None when there are none."""
    return next(iter(rows), None)


def reaches(rows: Sequence[AchievementRow], goal: int) -> AchievementRow | None:
    """The match on which the running ladder points reached the goal."""
    for row, total in zip(
        rows, accumulate(ladder.points(r.won, r.duration_s) for r in rows)
    ):
        if total >= goal:
            return row
    return None


def earned(
    rows: Sequence[AchievementRow],
    points: int,
    paid: PaidSet,
    opponents: frozenset[str] = frozenset(),
    captains: frozenset[str] = frozenset(),
    is_captain: bool = False,
    season: "Season | None" = None,
) -> list[Achievement]:
    """Every achievement one player earned, oldest first.

    `rows` are his scoped matches oldest first, `points` his ladder points,
    `paid` what this scope pays for each rule, and `opponents` and `captains`
    are battle tags in lower case. A rule the scope does not pay is not
    evaluated into the answer, so a season keeps only the rules it defines.
    Each badge names the match that turned its rule on.
    """
    # Each badge with the start of the match that earned it, for the sort
    found: list[tuple[datetime, Achievement]] = []

    def pay(
        rule: Achievement, at: AchievementRow | None, extra: int = 0, suffix: str = ""
    ) -> None:
        """Award a rule at what this scope pays for it, if it pays it at all."""
        price = paid.get(rule.id)
        if price is None or at is None:
            return
        badge = replace(
            rule,
            points=price + extra,
            description=rule.description + suffix,
            achieved_at=at.start_time,
        )
        found.append((at.start_time, badge))

    if rows:
        _wc3no(rows, points, paid, opponents, captains, is_captain, pay)
    if season is not None:
        # The off-race rules read their own rows, so a player with no match
        # on his league race can still earn them
        s19(rows, replace(season, is_captain=is_captain), pay)

    # Two badges of one instant keep the order the rules are evaluated in
    return [badge for _, badge in sorted(found, key=itemgetter(0))]


def _wc3no(
    rows: Sequence[AchievementRow],
    points: int,
    paid: PaidSet,
    opponents: frozenset[str],
    captains: frozenset[str],
    is_captain: bool,
    pay: Callable[..., None],
) -> None:
    """The 24 wc3.no rules over a player's matches, oldest first."""
    wins = [row for row in rows if row.won]
    losses = [row for row in rows if not row.won]
    beaten = [_tag(row) for row in wins]
    days = list(by_day(rows).values())
    daily_mmr = [sum(mmr_gain(row) for row in day) for day in days]

    kills = sum(1 for tag in beaten if tag in opponents)
    race = top_race(wins)

    pay(WIN_FIRST if rows[0].won else LOSE_FIRST, rows[0])
    pay(WINNER_WINNER, nth(wins, 100))
    pay(SAD_TROMBONE, nth(losses, 100))
    pay(ELITE, first(row for row in rows if row.mmr_after == ELITE_MMR))
    pay(DATS_FAKT_AP, run_end(rows, False, 10))
    pay(WIN_STREAK, run_end(rows, True, 5))
    pay(WIN_STREAK_2, run_end(rows, True, 10))
    if kills:
        kill = first(row for row in wins if _tag(row) in opponents)
        pay(DUCK_HUNTING, kill, 5 * kills, f" - {kills} kill(s)")
    if not is_captain:
        pay(I_AM_THE_CAPTAIN_NOW, first(row for row in wins if _tag(row) in captains))
    # Only the race beaten most pays, and only above 10 wins, not at 10
    if race is not None and race[1] > 10 and race[0] in RACE_ACHIEVEMENTS:
        eleventh = nth(
            [w for w in wins if w.opp_race and w.opp_race.value == race[0]], 11
        )
        pay(RACE_ACHIEVEMENTS[race[0]], eleventh, race[1], f" - {race[1]} wins!")
    pay(HOLIDAY, completes(wins, HOLIDAY_MAPS))
    pay(WINTER, completes(wins, WINTER_MAPS))
    pay(NEWBIE, completes(wins, NEW_MAPS))
    pay(WIN_EVERY_MAP, completes(wins, LADDER_MAPS))
    long_win = first(row for row in wins if row.duration_s > LONG_GAME_S)
    long_loss = first(row for row in losses if row.duration_s > LONG_GAME_S)
    if long_win is not None and long_loss is not None:
        pay(JOIN_THEM, max(long_win, long_loss, key=lambda row: row.start_time))
    pay(ADDICTED, first(day[29] for day in days if len(day) >= 30))
    pay(RISING_STAR, first(day[-1] for day, mmr in zip(days, daily_mmr) if mmr > 100))
    pay(FALLING_STAR, first(day[-1] for day, mmr in zip(days, daily_mmr) if mmr < -100))
    # `points` is the stored total, so it decides; the rows only date it
    if points >= LADDER_GOAL:
        pay(LADDER_GOAL_REACHED, reaches(rows, LADDER_GOAL) or rows[-1])
    if points >= LADDER_GOAL * 2:
        pay(DOUBLE_UP, reaches(rows, LADDER_GOAL * 2) or rows[-1])


DAY_S = 86400


@dataclass(frozen=True)
class Season:
    """What the S19 rules read beside one player's matches."""

    window: tuple[datetime, datetime] | None = None
    pool: Sequence[str] = ()
    # Tags in lower case: everyone on another team, on the player's own team,
    # and on any team; `team_of_tag` maps a tag to its team id
    opponents: frozenset[str] = frozenset()
    teammates: frozenset[str] = frozenset()
    members: frozenset[str] = frozenset()
    team_of_tag: dict[str, int] = field(default_factory=dict)
    own_team: int | None = None
    teams: int = 0
    league_race: str | None = None
    # The player's matches on every race, for the two off-race rules
    all_rows: Sequence[AchievementRow] = ()
    is_captain: bool = False
    is_first_to_fifty: bool = False

    @property
    def since_day(self) -> int:
        assert self.window is not None
        epoch = int(self.window[0].timestamp())
        return epoch - epoch % DAY_S

    @property
    def until(self) -> int:
        assert self.window is not None
        return int(self.window[1].timestamp())

    @property
    def weeks(self) -> int:
        assert self.window is not None
        return ceil(((self.window[1] - self.window[0]).days + 1) / 7)


def epoch(row: AchievementRow) -> int:
    return int(row.start_time.timestamp())


def weekend(row: AchievementRow) -> bool:
    """Saturday or Sunday, UTC."""
    return row.start_time.weekday() >= 5


def key(row: AchievementRow) -> tuple[datetime, int]:
    return (row.start_time, getattr(row, "id", 0) or 0)


def first_where(
    rows: Iterable[AchievementRow], test: Callable[[AchievementRow], bool]
) -> AchievementRow | None:
    return first(row for row in rows if test(row))


def nth_where(
    rows: Iterable[AchievementRow], n: int, test: Callable[[AchievementRow], bool]
) -> AchievementRow | None:
    return nth([row for row in rows if test(row)], n)


def group_nth(
    rows: Iterable[AchievementRow], n: int, by: Callable[[AchievementRow], object]
) -> AchievementRow | None:
    """The first group to collect n matches, dated by its nth."""
    groups: dict[object, list[AchievementRow]] = defaultdict(list)
    for row in rows:
        groups[by(row)].append(row)
    hits = [g[n - 1] for g in groups.values() if len(g) >= n]
    return min(hits, key=key) if hits else None


def covers(
    rows: Iterable[AchievementRow],
    by: Callable[[AchievementRow], object],
    values: Iterable[object],
    need: int | None = None,
) -> AchievementRow | None:
    """`need` of the values seen, dated by the first match on the last one."""
    wanted = set(values)
    need = len(wanted) if need is None else need
    firsts: dict[object, AchievementRow] = {}
    for row in rows:
        value = by(row)
        if value in wanted and value not in firsts:
            firsts[value] = row
            if len(firsts) == need:
                return row
    return None


def covers_count(
    rows: Iterable[AchievementRow],
    by: Callable[[AchievementRow], object | None],
    n: int,
) -> AchievementRow | None:
    """n distinct values, dated by the first match on the nth, ties by value."""
    firsts: dict[object, AchievementRow] = {}
    for row in rows:
        value = by(row)
        if value is not None and value not in firsts:
            firsts[value] = row
    ordered = sorted(
        firsts.items(), key=lambda item: (item[1].start_time, str(item[0]))
    )
    return ordered[n - 1][1] if len(ordered) >= n else None


def running_reaches(
    rows: Sequence[AchievementRow], term: Callable[[AchievementRow], int], target: int
) -> AchievementRow | None:
    for row, total in zip(rows, accumulate(term(r) for r in rows)):
        if total >= target:
            return row
    return None


def periods(
    rows: Sequence[AchievementRow],
    by: Callable[[AchievementRow], int],
    min_games: int,
    count: int,
    consecutive: bool = False,
) -> AchievementRow | None:
    """`count` periods of min_games matches, in a row when `consecutive`,
    dated by the match that qualified the last of them."""
    groups: dict[int, list[AchievementRow]] = defaultdict(list)
    for row in rows:
        groups[by(row)].append(row)
    qualified = {p: g[min_games - 1] for p, g in groups.items() if len(g) >= min_games}
    if not consecutive:
        ordered = sorted(qualified.values(), key=key)
        return ordered[count - 1] if len(ordered) >= count else None
    hits: list[AchievementRow] = []
    run: list[int] = []
    for p in sorted(qualified):
        run = [*run, p] if run and p == run[-1] + 1 else [p]
        if len(run) == count:
            hits.append(qualified[p])
    return min(hits, key=key) if hits else None


def within(
    rows: Sequence[AchievementRow], n: int, seconds: int
) -> AchievementRow | None:
    """n matches inside one window of this many seconds, dated by the first
    match with n-1 others in the window before it. Peers of one instant count
    on both sides, as a RANGE frame does."""
    hits = [
        row
        for row in rows
        if sum(
            1 for other in rows if epoch(row) - seconds <= epoch(other) <= epoch(row)
        )
        >= n
    ]
    return min(hits, key=key) if hits else None


def gaps(rows: Sequence[AchievementRow]) -> list[int | None]:
    return [None, *(epoch(b) - epoch(a) for a, b in pairwise(rows))]


def runs_of(
    rows: Sequence[AchievementRow], want: bool, length: int
) -> list[AchievementRow]:
    """The match that completed each separate run of `length`."""
    hits: list[AchievementRow] = []
    run = 0
    for row in rows:
        run = run + 1 if bool(row.won) == want else 0
        if run == length:
            hits.append(row)
    return hits


def rated(rows: Iterable[AchievementRow]) -> list[AchievementRow]:
    return [r for r in rows if r.mmr_before is not None and r.mmr_after is not None]


def _value(race: RaceValue | None) -> str | None:
    return race.value if race is not None else None


def s19(
    rows: Sequence[AchievementRow],
    season: Season,
    pay: Callable[..., None],
) -> None:
    """The S19 rules, in the order core.achievement_rules evaluates them."""
    wins = [row for row in rows if row.won]

    def tag(row: AchievementRow) -> str | None:
        return _tag(row) or None

    pay(GAMES_25, nth(rows, GAMES_TIERS[0]))
    pay(GAMES_50, nth(rows, GAMES_TIERS[1]))
    pay(GAMES_100, nth(rows, GAMES_TIERS[2]))
    pay(PLUS_TWENTY, running_reaches(rows, lambda r: 1 if r.won else -1, NET_WINS))
    pay(TWENTY_HOURS, running_reaches(rows, lambda r: r.duration_s, LADDER_SECONDS))
    day = lambda r: epoch(r) // DAY_S
    pay(STREAK_WEEK, periods(rows, day, 1, STREAK_DAYS, consecutive=True))
    pay(TWENTY_DAYS, periods(rows, day, 1, DISTINCT_DAYS))
    pay(FIVE_A_DAY, periods(rows, day, BUSY_DAY_GAMES, BUSY_DAYS))
    pay(
        WELCOME_BACK,
        first(
            row
            for row, gap in zip(rows, gaps(rows))
            if gap is not None and gap >= AWAY_DAYS * DAY_S
        ),
    )
    pay(ONE_SITTING, within(rows, SITTING_GAMES, SITTING_S))
    pay(POWER_HOUR, within(wins, HOUR_WINS, 3600))
    pay(WEEKEND_WARRIOR, nth_where(rows, WEEKEND_GAMES, weekend))
    completed = runs_of(rows, True, REPEAT_STREAK)
    pay(
        REPEAT_OFFENDER,
        completed[REPEAT_TIMES - 1] if len(completed) >= REPEAT_TIMES else None,
    )
    scored = rated(rows)
    afters = [int(r.mmr_after or 0) for r in scored]
    if scored and afters[-1] - int(scored[0].mmr_before or 0) >= CLIMB:
        pay(CLIMBER, scored[-1])
    if len(scored) >= HOLD_GAMES and max(afters) - afters[-1] <= HOLD_WITHIN:
        pay(HOLD_THE_LINE, scored[-1])
    pay(HOME_TURF, group_nth(wins, HOME_WINS, lambda r: r.map_name))
    pay(RACE_TOUR, covers(wins, lambda r: _value(r.opp_race), RACE_ACHIEVEMENTS))
    mirror = lambda r: (
        r.played_race is not None and _value(r.played_race) == _value(r.opp_played_race)
    )
    pay(MIRROR_MASTER, nth_where(wins, MIRROR_WINS, mirror))
    pay(
        ANTI_RANDOM,
        nth_where(wins, RANDOM_WINS, lambda r: _value(r.opp_race) == "RANDOM"),
    )
    for code, rule in SLAYERS.items():
        versus = [r for r in rows if _value(r.opp_race) == code]
        won = sum(1 for r in versus if r.won)
        if len(versus) >= SLAYER_GAMES and won * 100 >= len(versus) * int(
            SLAYER_RATE * 100
        ):
            pay(rule, max(versus, key=key))
    pay(NEMESIS, group_nth([r for r in wins if tag(r)], NEMESIS_WINS, tag))
    pay(RIVAL, group_nth([r for r in rows if tag(r)], RIVAL_GAMES, tag))
    pay(WIDE_NET, covers_count(wins, tag, WIDE_NET_N))
    pay(SPEEDRUNNER, first_where(wins, lambda r: r.duration_s <= SPEEDRUN_S))
    pay(MARATHON, first_where(rows, lambda r: r.duration_s >= MARATHON_S))
    if season.is_first_to_fifty:
        pay(FIRST_TO_FIFTY, nth(rows, 50))

    if season.window is not None:
        since = season.since_day

        def day_index(r: AchievementRow) -> int:
            return (epoch(r) // DAY_S * DAY_S - since) // DAY_S

        week = lambda r: day_index(r) // 7
        pay(EARLY_BIRD, first_where(rows, lambda r: day_index(r) < EARLY_DAYS))
        pay(WEEK_ONE, nth_where(rows, WEEK_ONE_GAMES, lambda r: day_index(r) < 7))
        pay(
            LAST_CALL,
            first_where(rows, lambda r: epoch(r) > season.until - LAST_DAYS * DAY_S),
        )
        pay(ALWAYS_HERE, periods(rows, week, 1, season.weeks))
        pay(WEEKLY_REGULAR, periods(rows, week, WEEKLY_GAMES, WEEKLY_WEEKS))
        pay(
            MONTH_OF_SUNDAYS,
            periods(
                [r for r in rows if weekend(r)],
                week,
                1,
                WEEKEND_WEEKS,
                consecutive=True,
            ),
        )
        breaks: list[int] = [g for g in gaps(rows) if g is not None]
        if (
            len(rows) >= GONE_GAMES
            and max(breaks, default=0) <= GONE_DAYS * DAY_S
            and epoch(rows[0]) <= since + GONE_DAYS * DAY_S
            and epoch(rows[-1]) >= season.until - GONE_DAYS * DAY_S
        ):
            pay(NEVER_GONE, rows[-1])
    if season.pool:
        pay(WIN_POOL, covers(wins, lambda r: r.map_name, season.pool))
        pay(TOURIST, covers(rows, lambda r: r.map_name, season.pool))
    if season.members:
        pay(HUNTING_SEASON, first_where(wins, lambda r: _tag(r) in season.opponents))
        pay(
            OPEN_SEASON,
            covers_count(
                [r for r in wins if _tag(r) in season.members], tag, OPEN_SEASON_N
            ),
        )
        pay(CIVIL_WAR, first_where(wins, lambda r: _tag(r) in season.teammates))
    if season.teams > 1:
        other = lambda r: season.team_of_tag.get(_tag(r))
        pay(
            GRAND_TOUR,
            covers(
                [
                    r
                    for r in wins
                    if other(r) is not None and other(r) != season.own_team
                ],
                other,
                set(season.team_of_tag.values()),
                need=season.teams - 1,
            ),
        )
    if season.is_captain:
        pay(CAPTAINS_DUTY, nth(rows, CAPTAIN_GAMES))
    if season.all_rows:
        every = [r for r in season.all_rows if r.won]
        pay(
            FOUR_HORSEMEN,
            covers(every, lambda r: _value(r.played_race), RACE_ACHIEVEMENTS),
        )
        if season.league_race:
            pay(
                OFF_DUTY,
                first_where(
                    every,
                    lambda r: (
                        r.race is not None and _value(r.race) != season.league_race
                    ),
                ),
            )


def _tag(row: AchievementRow) -> str:
    """The opponent's battle tag in lower case, the shape the tag sets hold."""
    return (row.opp_battletag or "").lower()
