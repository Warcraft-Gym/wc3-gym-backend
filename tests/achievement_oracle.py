"""The achievement rules in Python, the oracle the SQL is proved against.

This was app/core/achievements.earned: the rule set read out of the wc3.no
bundle, evaluated over one player's ordered matches. The application answers
the badges from core.achievement_rules in SQL now, so the two are compared
over random match sequences in tests/test_achievement_parity.py.
"""

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import replace
from datetime import date, datetime
from itertools import accumulate
from operator import itemgetter
from typing import Protocol

from app.core import ladder
from app.core.achievements import (
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
    def opp_race(self) -> RaceValue | None: ...
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
) -> list[Achievement]:
    """Every achievement one player earned, oldest first.

    `rows` are his scoped matches oldest first, `points` his ladder points,
    `paid` what this scope pays for each rule, and `opponents` and `captains`
    are battle tags in lower case. A rule the scope does not pay is not
    evaluated into the answer, so a season keeps only the rules it defines.
    Each badge names the match that turned its rule on.
    """
    if not rows:
        # No match means no first game, and 0 points reaches no goal
        return []

    wins = [row for row in rows if row.won]
    losses = [row for row in rows if not row.won]
    beaten = [_tag(row) for row in wins]
    days = list(by_day(rows).values())
    daily_mmr = [sum(mmr_gain(row) for row in day) for day in days]

    kills = sum(1 for tag in beaten if tag in opponents)
    race = top_race(wins)

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

    return [badge for _, badge in sorted(found, key=itemgetter(0))]


def _tag(row: AchievementRow) -> str:
    """The opponent's battle tag in lower case, the shape the tag sets hold."""
    return (row.opp_battletag or "").lower()
