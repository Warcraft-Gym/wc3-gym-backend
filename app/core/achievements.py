"""The GNL ladder achievements, as wc3.no computes them.

The 24 rules and their conditions were read out of the wc3.no production
bundle (`assets/index-CKpjbYLg.js`), set `gnl_season_16`: the definitions
object holds id, points, icon, name and description, and one `calculate`
function holds every condition. This module is that object in Python, and
core.achievement_rules is that function in SQL, so the totals here equal the
totals wc3.no publishes.

A rule reads the same rows the ladder totals read: the player's matches on
his league race, longer than core.ladder.MIN_DURATION_S, inside the window,
oldest first. Four rules read more than that: the player's ladder points, the
tags of the players on the other teams, the tags of the season's captains,
and whether the player captains himself.

Three rules pay a variable amount, exactly as the bundle does: duck_hunting
adds 5 per kill and the race rule adds 1 per win, both on top of the base,
and only the single race the player beat most often ever pays.

Two rules read a day. The bundle buckets by the UTC day a match ended on and
this module by the day it started on, because the table keeps a start time.
"""

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import datetime

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
    # When the rule turned on: the start of the match that earned it, the
    # last match of the day for the day rules, None on a catalogue entry
    achieved_at: datetime | None = None


# What a scope pays for each rule it pays at all, keyed by rule id. A rule
# missing from the map is a rule this scope does not run.
PaidSet = Mapping[str, int]


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
    "holiday", 5, "I'm on holiday!", "Win a game on Tidehunters", "mdi-palm-tree"
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


def total_points(found: Iterable[Achievement]) -> int:
    """What a player's achievements add to his ladder points."""
    return sum(item.points for item in found)


# What a season pays when nobody has changed it: the wc3.no set, at its own
# prices. The migration seeds every season with exactly this.
DEFAULT_PAID: PaidSet = {rule.id: rule.points for rule in ACHIEVEMENTS}
