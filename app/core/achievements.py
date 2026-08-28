"""The GNL ladder achievements, as wc3.no computes them.

The 24 rules and their conditions were read out of the wc3.no production
bundle (`assets/index-CKpjbYLg.js`), set `gnl_season_16`: the definitions
object holds id, points, icon, name and description, and one `calculate`
function holds every condition. This module is that function in Python, so
the totals here equal the totals wc3.no publishes.

A rule reads the same rows the ladder totals read: the player's matches on
his league race, longer than core.ladder.MIN_DURATION_S, inside the window,
oldest first. Four rules read more than that and take it as arguments: the
player's ladder points, the tags of the players on the other teams, the tags
of the season's coaches, and whether the player coaches himself.

Three rules pay a variable amount, exactly as the bundle does: duck_hunting
adds 5 per kill and the race rule adds 1 per win, both on top of the base,
and only the single race the player beat most often ever pays.

Two rules read a day. The bundle buckets by the UTC day a match ended on and
this module by the day it started on, because the table keeps a start time.
"""

from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime
from typing import Protocol

# The season's points target, hardcoded as `W1=500` in the wc3.no bundle
LADDER_GOAL = 500

# The map lists the bundle carries, by their w3champions `mapName`
HOLIDAY_MAPS = ("Tidehunters",)
WINTER_MAPS = ("Northern Isles", "Melting Valley v2", "Springtime")
NEW_MAPS = ("War Hail", "Melting Valley v2", "Secret Valley v2", "Boulder Vale")
LADDER_MAPS = (
    "Autumn Leaves v2",
    "Concealed Hill",
    "Hammerfall",
    "Last Refuge",
    "Northern Isles",
    "Shallow Grave",
    "Springtime",
    "Tidehunters",
    "War Hail",
    "Secret Valley v2",
    "Melting Valley v2",
    "Boulder Vale",
)

# The MMR the elite rule wants hit exactly
ELITE_MMR = 1337
# A long game, for the rule that wants one won and one lost
LONG_GAME_S = 30 * 60


@dataclass(frozen=True)
class Achievement:
    """One rule: what it is worth and how the badge reads."""

    id: str
    points: int
    name: str
    description: str
    icon: str


# What a scope pays for each rule it pays at all, keyed by rule id. A rule
# missing from the map is a rule this scope does not run.
PaidSet = Mapping[str, int]


class RaceValue(Protocol):
    """A race the way the models spell it, for example Race.NE."""

    value: str


class AchievementRow(Protocol):
    """What the rules read off a match, stored or straight from w3champions."""

    won: bool
    start_time: datetime
    duration_s: int
    map_name: str | None
    opp_race: RaceValue | None
    opp_battletag: str | None
    mmr_before: int | None
    mmr_after: int | None


WIN_FIRST = Achievement(
    "win_first", 15, "I am the danger!", "Win your first GNL game", "mdi-redhat"
)
LOSE_FIRST = Achievement(
    "lose_first",
    25,
    "When I'm In Command, Every Mission Is A Suicide Mission.",
    "Lose your first GNL game",
    "mdi-skull",
)
WINNER_WINNER = Achievement(
    "winner_winner",
    50,
    "Winner winner chicken dinner!",
    "Win 100 games",
    "mdi-food-drumstick",
)
SAD_TROMBONE = Achievement(
    "sad_trombone", 50, "Sad Trombone", "Lose 100 games", "mdi-trumpet"
)
ELITE = Achievement(
    "elite", 100, "1337", "Get your MMR to 1337", "mdi-emoticon-cool-outline"
)
DATS_FAKT_AP = Achievement(
    "dats_fakt_ap", 50, "DATS FAKT AP", "Lose 10 games in a row", "mdi-egg"
)
WIN_STREAK = Achievement(
    "win_streak", 25, "Connect Five!", "Win 5 games in a row", "mdi-tally-mark-5"
)
WIN_STREAK_2 = Achievement(
    "win_streak_2", 50, "Who can stop me?!", "Win 10 games in a row", "mdi-karate"
)
DUCK_HUNTING = Achievement(
    "duck_hunting",
    10,
    "Hunting Season!",
    "Defeat a player from an opposing team",
    "mdi-target-account",
)
I_AM_THE_CAPTAIN_NOW = Achievement(
    "i_am_the_captain_now",
    100,
    "I'm the captain now!",
    "Win a ladder game vs. a GNL coach!",
    "mdi-ferry",
)
NIGHT_ELF = Achievement(
    "night_elf",
    10,
    "Destroyer of Trees",
    "Win 10+ games vs. Night Elf",
    "mdi-shield-moon",
)
UNDEAD = Achievement(
    "undead", 10, "Bane of the Scourge", "Win 10+ games vs. Undead", "mdi-ghost-outline"
)
ORC = Achievement(
    "orc", 10, "Reaper of Greenskins", "Win 10+ games vs. Orc", "mdi-paw-outline"
)
HUMAN = Achievement(
    "human", 10, "A plague upon Humanity", "Win 10+ games vs. Human", "mdi-wizard-hat"
)
HOLIDAY = Achievement(
    "holiday", 5, "I'm on holiday!", "Win a game on Tide Hunters", "mdi-palm-tree"
)
WINTER = Achievement(
    "winter",
    10,
    "A true Stark",
    "Win a game on every winter map",
    "mdi-weather-snowy-heavy",
)
NEWBIE = Achievement(
    "newbie",
    5,
    "Don’t be afraid to try something new!",
    "Win a game on every NEW map!",
    "mdi-new-box",
)
WIN_EVERY_MAP = Achievement(
    "win_every_map",
    25,
    "Dora the explorer",
    "Win a game on every ladder map",
    "mdi-map-check",
)
JOIN_THEM = Achievement(
    "join_them",
    10,
    "If you can't beat them...",
    "Win and Lose a game that lasted over 30min",
    "mdi-handshake",
)
ADDICTED = Achievement(
    "addicted",
    100,
    "Better Living Through Chemistry",
    "Play 30 games in 24-hour span",
    "mdi-flask",
)
RISING_STAR = Achievement(
    "rising_star",
    25,
    "I know kung fu",
    "Earn over 100 MMR in a single day",
    "mdi-brain",
)
FALLING_STAR = Achievement(
    "falling_star",
    25,
    "Did you even say thank you?",
    "Lose over 100 MMR in a single day",
    "mdi-account-tie",
)
LADDER_GOAL_REACHED = Achievement(
    "ladder_goal",
    500,
    "The end of a journey holds the seed of new dreams!",
    "Reach this seasons ladder goal!",
    "mdi-seed-plus",
)
DOUBLE_UP = Achievement(
    "double_up",
    1000,
    "Double Up On The Bubble Up",
    "Reach this seasons ladder goal! TWICE!",
    "mdi-chart-bubble",
)

ACHIEVEMENTS = [
    LADDER_GOAL_REACHED,
    DOUBLE_UP,
    I_AM_THE_CAPTAIN_NOW,
    ADDICTED,
    ELITE,
    DATS_FAKT_AP,
    WINNER_WINNER,
    SAD_TROMBONE,
    WIN_STREAK_2,
    WIN_FIRST,
    LOSE_FIRST,
    WIN_STREAK,
    WIN_EVERY_MAP,
    RISING_STAR,
    FALLING_STAR,
    DUCK_HUNTING,
    NIGHT_ELF,
    UNDEAD,
    ORC,
    HUMAN,
    JOIN_THEM,
    WINTER,
    HOLIDAY,
    NEWBIE,
]

# The rule pays for one race only, so the race the player beat most is looked
# up here. Random is in no bucket and pays nothing.
RACE_ACHIEVEMENTS = {"HU": HUMAN, "OC": ORC, "NE": NIGHT_ELF, "UD": UNDEAD}

# The w3champions race ids; the bundle gives a tie to the lowest of them
RACE_IDS = {"RANDOM": 0, "HU": 1, "OC": 2, "NE": 4, "UD": 8}


def longest_run(results: Sequence[bool], want: bool) -> int:
    """The longest run of `want` in a sequence of results."""
    best = run = 0
    for result in results:
        run = run + 1 if result == want else 0
        best = max(best, run)
    return best


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


def earned(
    rows: Sequence[AchievementRow],
    points: int,
    paid: PaidSet,
    opponents: frozenset[str] = frozenset(),
    coaches: frozenset[str] = frozenset(),
    is_coach: bool = False,
) -> list[Achievement]:
    """Every achievement one player earned, worth most first.

    `rows` are his scoped matches oldest first, `points` his ladder points,
    `paid` what this scope pays for each rule, and `opponents` and `coaches`
    are battle tags in lower case. A rule the scope does not pay is not
    evaluated into the answer, so a season keeps only the rules it defines.
    """
    if not rows:
        # No match means no first game, and 0 points reaches no goal
        return []

    wins = [row for row in rows if row.won]
    losses = [row for row in rows if not row.won]
    results = [bool(row.won) for row in rows]
    won_maps = {row.map_name for row in wins}
    beaten = [_tag(row) for row in wins]
    days = by_day(rows)
    daily_mmr = [sum(mmr_gain(row) for row in day) for day in days.values()]

    kills = sum(1 for tag in beaten if tag in opponents)
    race = top_race(wins)

    found: list[Achievement] = []

    def pay(rule: Achievement, extra: int = 0, suffix: str = "") -> None:
        """Award a rule at what this scope pays for it, if it pays it at all."""
        price = paid.get(rule.id)
        if price is None:
            return
        found.append(
            replace(
                rule,
                points=price + extra,
                description=rule.description + suffix,
            )
        )

    pay(WIN_FIRST if rows[0].won else LOSE_FIRST)
    if len(wins) >= 100:
        pay(WINNER_WINNER)
    if len(losses) >= 100:
        pay(SAD_TROMBONE)
    if any(row.mmr_after == ELITE_MMR for row in rows):
        pay(ELITE)
    if longest_run(results, False) >= 10:
        pay(DATS_FAKT_AP)
    if longest_run(results, True) >= 5:
        pay(WIN_STREAK)
    if longest_run(results, True) >= 10:
        pay(WIN_STREAK_2)
    if kills:
        pay(DUCK_HUNTING, 5 * kills, f" - {kills} kill(s)")
    if not is_coach and any(tag in coaches for tag in beaten):
        pay(I_AM_THE_CAPTAIN_NOW)
    # Only the race beaten most pays, and only above 10 wins, not at 10
    if race is not None and race[1] > 10 and race[0] in RACE_ACHIEVEMENTS:
        pay(RACE_ACHIEVEMENTS[race[0]], race[1], f" - {race[1]} wins!")
    if won_maps.issuperset(HOLIDAY_MAPS):
        pay(HOLIDAY)
    if won_maps.issuperset(WINTER_MAPS):
        pay(WINTER)
    if won_maps.issuperset(NEW_MAPS):
        pay(NEWBIE)
    if won_maps.issuperset(LADDER_MAPS):
        pay(WIN_EVERY_MAP)
    if _longest(wins) > LONG_GAME_S and _longest(losses) > LONG_GAME_S:
        pay(JOIN_THEM)
    if max(len(day) for day in days.values()) >= 30:
        pay(ADDICTED)
    if max(daily_mmr) > 100:
        pay(RISING_STAR)
    if min(daily_mmr) < -100:
        pay(FALLING_STAR)
    if points >= LADDER_GOAL:
        pay(LADDER_GOAL_REACHED)
    if points >= LADDER_GOAL * 2:
        pay(DOUBLE_UP)

    found.sort(key=lambda item: -item.points)
    return found


def total_points(found: Iterable[Achievement]) -> int:
    """What a player's achievements add to his ladder points."""
    return sum(item.points for item in found)


def _tag(row: AchievementRow) -> str:
    """The opponent's battle tag in lower case, the shape the tag sets hold."""
    return (row.opp_battletag or "").lower()


def _longest(rows: Sequence[AchievementRow]) -> int:
    """The longest of these matches in seconds, 0 when there are none."""
    return max((row.duration_s for row in rows), default=0)


# What a season pays when nobody has changed it: the wc3.no set, at its own
# prices. The migration seeds every season with exactly this.
DEFAULT_PAID: PaidSet = {rule.id: rule.points for rule in ACHIEVEMENTS}
