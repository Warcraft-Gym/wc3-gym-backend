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
from dataclasses import dataclass, replace
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
    "win_first", 3, "I am the danger!", "Win your first game", "mdi-redhat"
)
LOSE_FIRST = Achievement(
    "lose_first",
    5,
    "Suicide mission",
    "Lose your first game",
    "mdi-skull",
)
WINNER_WINNER = Achievement(
    "winner_winner",
    40,
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
    "win_streak", 3, "Connect Five!", "Win 5 games in a row", "mdi-tally-mark-5"
)
WIN_STREAK_2 = Achievement(
    "win_streak_2", 40, "Who can stop me?!", "Win 10 games in a row", "mdi-karate"
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
    50,
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
    100,
    "The end of a journey holds the seed of new dreams!",
    "Reach this seasons ladder goal!",
    "mdi-seed-plus",
)
DOUBLE_UP = Achievement(
    "double_up",
    250,
    "Double Up On The Bubble Up",
    "Reach this seasons ladder goal! TWICE!",
    "mdi-chart-bubble",
)


# ---- The S19 set. Prices are small on purpose: a win pays 3 ladder points and a
# loss 1, so a badge is worth a game or two, and lose_first pays win_first + 2 so
# the first game breaks even either way.

# Days from the season start an early game may fall on, and games in week one
EARLY_DAYS = 3
WEEK_ONE_GAMES = 5
# Days before the season end a last-call game may fall on
LAST_DAYS = 3
# The games behind each volume badge
GAMES_TIERS = (25, 50, 100)
# Wins over losses for the margin badge
NET_WINS = 20
# Seconds on the ladder for the hours badge
LADDER_SECONDS = 20 * 3600
# Days in a row, distinct days, and busy days the day badges want
STREAK_DAYS = 7
DISTINCT_DAYS = 20
BUSY_DAYS = 10
BUSY_DAY_GAMES = 5
# Weeks with WEEKLY_GAMES games for the regular badge
WEEKLY_WEEKS = 4
WEEKLY_GAMES = 5
# Weekends in a row with a game
WEEKEND_WEEKS = 4
# The longest break allowed, and the games needed, to never be gone
GONE_DAYS = 5
GONE_GAMES = 20
# Days away before a return counts
AWAY_DAYS = 14
# Games inside one sitting, and the sitting's length in seconds
SITTING_GAMES = 5
SITTING_S = 3 * 3600
# Wins inside one hour
HOUR_WINS = 3
# Games on weekends
WEEKEND_GAMES = 10
# Three separate streaks of this length
REPEAT_STREAK = 3
REPEAT_TIMES = 3
# MMR gained from the first game to the last
CLIMB = 100
# Games played and MMR under the peak to hold the line
HOLD_GAMES = 30
HOLD_WITHIN = 20
# MMR gained from the season low to the finish, over HOLD_GAMES games
COMEBACK_GAIN = 100
# Wins on one map
HOME_WINS = 10
# Mirror wins, and wins over Random players
MIRROR_WINS = 5
RANDOM_WINS = 5
# Games against one race and the share won to slay it
SLAYER_GAMES = 10
SLAYER_RATE = 0.7
# Wins and games over one opponent, and distinct opponents beaten
NEMESIS_WINS = 3
RIVAL_GAMES = 5
WIDE_NET_N = 20
# Distinct GNL players beaten
OPEN_SEASON_N = 5
# A short win and a long game, in seconds
SPEEDRUN_S = 7 * 60
MARATHON_S = 45 * 60
# Games a captain plays
CAPTAIN_GAMES = 20
# The race to this many games
FIRST_TO = 50

EARLY_BIRD = Achievement(
    "early_bird",
    2,
    "Early bird",
    "Play a game in the first 3 days of the season",
    "game-icons:hummingbird",
)
WEEK_ONE = Achievement(
    "week_one",
    3,
    "Week one warrior",
    "Play 5 games in the first week",
    "game-icons:spartan-helmet",
)
LAST_CALL = Achievement(
    "last_call",
    2,
    "Last call",
    "Play a game in the last 3 days of the season",
    "game-icons:hourglass",
)
GAMES_25 = Achievement(
    "games_25", 2, "Regular", "Play 25 games", "game-icons:card-play"
)
GAMES_50 = Achievement("games_50", 3, "Grinder", "Play 50 games", "game-icons:gears")
GAMES_100 = Achievement(
    "games_100", 8, "No-lifer", "Play 100 games", "game-icons:night-sleep"
)
PLUS_TWENTY = Achievement(
    "plus_twenty",
    25,
    "Plus twenty",
    "Get 20 more wins than losses",
    "game-icons:health-increase",
)
TWENTY_HOURS = Achievement(
    "twenty_hours",
    5,
    "Twenty hours",
    "Spend 20 hours in ladder games",
    "game-icons:pocket-watch",
)
STREAK_WEEK = Achievement(
    "streak_week", 5, "Streak week", "Play on 7 days in a row", "game-icons:calendar"
)
TWENTY_DAYS = Achievement(
    "twenty_days",
    5,
    "Twenty days",
    "Play on 20 different days",
    "game-icons:sands-of-time",
)
FIVE_A_DAY = Achievement(
    "five_a_day",
    8,
    "Five a day",
    "Play 5 or more games on 10 different days",
    "game-icons:shiny-apple",
)
ALWAYS_HERE = Achievement(
    "always_here",
    5,
    "Always here",
    "Play at least one game in every week of the season",
    "game-icons:lighthouse",
)
WEEKLY_REGULAR = Achievement(
    "weekly_regular",
    4,
    "Weekly regular",
    "Play 5 or more games in 4 different weeks",
    "game-icons:stopwatch",
)
MONTH_OF_SUNDAYS = Achievement(
    "month_of_sundays",
    8,
    "Month of Sundays",
    "Play on 4 weekends in a row",
    "game-icons:sun",
)
NEVER_GONE = Achievement(
    "never_gone",
    10,
    "Never gone",
    "Never go 5 days without a game, from the first week to the last",
    "game-icons:campfire",
)
WELCOME_BACK = Achievement(
    "welcome_back",
    2,
    "Welcome back",
    "Play again after 14 days away",
    "game-icons:return-arrow",
)
ONE_SITTING = Achievement(
    "one_sitting",
    2,
    "One sitting",
    "Play 5 games inside 3 hours",
    "game-icons:armchair",
)
POWER_HOUR = Achievement(
    "power_hour",
    2,
    "Power hour",
    "Win 3 games inside one hour",
    "game-icons:lightning-trio",
)
WEEKEND_WARRIOR = Achievement(
    "weekend_warrior",
    3,
    "Weekend warrior",
    "Play 10 games on Saturdays and Sundays",
    "game-icons:barbecue",
)
REPEAT_OFFENDER = Achievement(
    "repeat_offender",
    3,
    "Repeat offender",
    "Win 3 in a row, three separate times",
    "game-icons:handcuffs",
)
CLIMBER = Achievement(
    "climber",
    15,
    "Climber",
    "Finish the season 100 MMR above where you started",
    "game-icons:mountain-climbing",
)
HOLD_THE_LINE = Achievement(
    "hold_the_line",
    15,
    "Hold the line",
    "Play 30 games and finish within 20 MMR of your season high",
    "game-icons:shield",
)
WIN_POOL = Achievement(
    "win_pool",
    15,
    "Win every map",
    "Win a game on every map in this season's pool",
    "game-icons:treasure-map",
)
TOURIST = Achievement(
    "tourist",
    8,
    "Tourist",
    "Play a game on every map in this season's pool",
    "game-icons:suitcase",
)
HOME_TURF = Achievement(
    "home_turf", 5, "Home turf", "Win 10 games on one map", "game-icons:castle"
)
RACE_TOUR = Achievement(
    "race_tour", 2, "Race tour", "Beat every race", "game-icons:world"
)
MIRROR_MASTER = Achievement(
    "mirror_master",
    3,
    "Mirror master",
    "Win 5 mirror matches",
    "game-icons:mirror-mirror",
)
ANTI_RANDOM = Achievement(
    "anti_random",
    5,
    "Anti-random",
    "Beat 5 players who picked Random",
    "game-icons:perspective-dice-six-faces-random",
)
SLAYER_HU = Achievement(
    "slayer_hu",
    25,
    "Human slayer",
    "Win 70% of 10 or more games against Human",
    "game-icons:crowned-skull",
)
SLAYER_OC = Achievement(
    "slayer_oc",
    25,
    "Orc slayer",
    "Win 70% of 10 or more games against Orc",
    "game-icons:orc-head",
)
SLAYER_NE = Achievement(
    "slayer_ne",
    25,
    "Night Elf slayer",
    "Win 70% of 10 or more games against Night Elf",
    "game-icons:elf-helmet",
)
SLAYER_UD = Achievement(
    "slayer_ud",
    25,
    "Undead slayer",
    "Win 70% of 10 or more games against Undead",
    "game-icons:shambling-zombie",
)
FOUR_HORSEMEN = Achievement(
    "four_horsemen",
    15,
    "Four horsemen",
    "Win a game as each of the four races",
    "game-icons:mounted-knight",
)
OFF_DUTY = Achievement(
    "off_duty",
    5,
    "Off duty",
    "Win a game on a race that is not your league race",
    "game-icons:beach-bag",
)
NEMESIS = Achievement(
    "nemesis", 5, "Nemesis", "Beat the same opponent 3 times", "game-icons:daggers"
)
RIVAL = Achievement(
    "rival", 5, "Rival", "Play the same opponent 5 times", "game-icons:crossed-swords"
)
WIDE_NET = Achievement(
    "wide_net", 3, "Wide net", "Beat 20 different opponents", "game-icons:fishing-net"
)
HUNTING_SEASON = Achievement(
    "hunting_season",
    3,
    "Hunting season",
    "Beat a player from another team",
    "game-icons:duck",
)
OPEN_SEASON = Achievement(
    "open_season",
    20,
    "Open season",
    "Beat 5 different GNL players",
    "game-icons:crosshair",
)
CIVIL_WAR = Achievement(
    "civil_war", 5, "Civil war", "Beat a teammate", "game-icons:two-shadows"
)
GRAND_TOUR = Achievement(
    "grand_tour",
    75,
    "Grand tour",
    "Beat a player from every other team",
    "game-icons:trophy-cup",
)
SPEEDRUNNER = Achievement(
    "speedrunner",
    2,
    "Speedrunner",
    "Win a game in under 7 minutes",
    "game-icons:running-shoe",
)
MARATHON = Achievement(
    "marathon",
    3,
    "Marathon",
    "Play a game longer than 45 minutes",
    "game-icons:tortoise",
)
CAPTAINS_DUTY = Achievement(
    "captains_duty",
    25,
    "Captain's duty",
    "Play 20 games as a captain",
    "game-icons:captain-hat-profile",
)
FIRST_TO_FIFTY = Achievement(
    "first_to_fifty",
    50,
    "First to fifty",
    "Be the first player of the season to reach 50 games",
    "game-icons:finish-line",
)

# Team badges: paid to the team, never a player. `subject` tells them apart.
FULL_ROSTER = Achievement(
    "full_roster",
    25,
    "Full roster",
    "Every player on the team played 10 or more games",
    "game-icons:team-idea",
)
EVERYONE_SCORES = Achievement(
    "everyone_scores",
    15,
    "Everyone scores",
    "Every player on the team won at least one game",
    "game-icons:podium-winner",
)
HALF_REGULAR = Achievement(
    "half_regular",
    25,
    "Half regular",
    "Half the team earned Weekly regular",
    "game-icons:half-heart",
)
EVERY_WEEK = Achievement(
    "every_week",
    25,
    "Every week",
    "In every week of the season, 3 or more players played 3 or more games",
    "game-icons:calendar-half-year",
)
NEVER_BLANK = Achievement(
    "never_blank",
    15,
    "Never blank",
    "In every week of the season, somebody on the team won",
    "game-icons:checkered-flag",
)
FAST_START = Achievement(
    "fast_start",
    15,
    "Fast start",
    "Every player on the team played in the first week",
    "game-icons:sprint",
)
NOBODY_LEFT = Achievement(
    "nobody_left",
    15,
    "Nobody left",
    "Every player on the team played in the last week",
    "game-icons:exit-door",
)
TEAM_NIGHT = Achievement(
    "team_night",
    15,
    "Team night",
    "The team played 30 games in one day, from 5 or more players",
    "game-icons:moon",
)
TEAM_MAP_COVERAGE = Achievement(
    "team_map_coverage",
    25,
    "Team map coverage",
    "The team won on every map in the season's pool",
    "game-icons:compass",
)
TEAM_RACE_COVERAGE = Achievement(
    "team_race_coverage",
    15,
    "Team race coverage",
    "The team beat every race",
    "game-icons:swords-emblem",
)
TEAM_GRAND_TOUR = Achievement(
    "team_grand_tour",
    25,
    "Team grand tour",
    "The team beat a player from every other team",
    "game-icons:laurels-trophy",
)
FIFTY_FACES = Achievement(
    "fifty_faces",
    15,
    "Fifty faces",
    "The team beat 50 different opponents",
    "game-icons:three-friends",
)
TEAM_GOAL = Achievement(
    "team_goal",
    25,
    "Team goal",
    "The team's ladder points add up to 1000, counting at most 150 per player",
    "game-icons:goal-keeper",
)
TWO_HUNDRED = Achievement(
    "two_hundred",
    15,
    "Two hundred",
    "The team played 200 games, counting at most 30 per player",
    "game-icons:abacus",
)
TEAM_CLIMB = Achievement(
    "team_climb",
    25,
    "Team climb",
    "The team gained 500 MMR, counting at most 100 per player",
    "game-icons:stairs-goal",
)
BRAGGING_RIGHTS = Achievement(
    "bragging_rights",
    15,
    "Bragging rights",
    "The team beat one other team 20 times",
    "game-icons:trumpet-flag",
)
SPARRING_PARTNERS = Achievement(
    "sparring_partners",
    10,
    "Sparring partners",
    "Teammates played each other 10 times",
    "game-icons:boxing-glove",
)
EVERYONE_HUNTS = Achievement(
    "everyone_hunts",
    25,
    "Everyone hunts",
    "Every player on the team beat a player from another team",
    "game-icons:hunting-horn",
)

# The team folds that read a per-player number: games, wins, points, or MMR gained
ROSTER_GAMES = 10
TEAM_WEEK_PLAYERS = 3
TEAM_WEEK_GAMES = 3
TEAM_NIGHT_GAMES = 30
TEAM_NIGHT_PLAYERS = 5
FIFTY_FACES_N = 50
TEAM_GOAL_CAP, TEAM_GOAL_TARGET = 150, 1000
TWO_HUNDRED_CAP, TWO_HUNDRED_TARGET = 30, 200
TEAM_CLIMB_CAP, TEAM_CLIMB_TARGET = 100, 500
BRAGGING_WINS = 20
SPARRING_GAMES = 10

HAT_TRICK = Achievement(
    "hat_trick", 2, "Hat-trick", "Win 3 games in a row", "game-icons:top-hat"
)
REVENGE = Achievement(
    "revenge",
    3,
    "Revenge",
    "Beat an opponent who beat you earlier this season",
    "game-icons:backstab",
)
COMEBACK = Achievement(
    "comeback",
    8,
    "Comeback",
    "Play 30 games and finish 100 MMR above your season low",
    "game-icons:sunrise",
)
# One badge per map of the season's pool, id `map_win:<map>`; see per_map
MAP_WIN = Achievement(
    "map_win", 2, "Map win", "Win a game on a map", "game-icons:position-marker"
)


def per_map(map_name: str) -> Achievement:
    """The MAP_WIN badge of one map; the price row is MAP_WIN's."""
    return replace(
        MAP_WIN,
        id=f"{MAP_WIN.id}:{map_name}",
        name=f"Win on {map_name}",
        description=f"Win a game on {map_name}",
    )


def priced_id(rule_id: str) -> str:
    """The catalogue id a badge id is priced by: `map_win:<map>` is map_win."""
    return rule_id.partition(":")[0]


S19_PLAYER = [
    WIN_FIRST,
    LOSE_FIRST,
    EARLY_BIRD,
    WEEK_ONE,
    LAST_CALL,
    GAMES_25,
    GAMES_50,
    GAMES_100,
    WINNER_WINNER,
    PLUS_TWENTY,
    TWENTY_HOURS,
    STREAK_WEEK,
    TWENTY_DAYS,
    FIVE_A_DAY,
    ALWAYS_HERE,
    WEEKLY_REGULAR,
    MONTH_OF_SUNDAYS,
    NEVER_GONE,
    WELCOME_BACK,
    ONE_SITTING,
    POWER_HOUR,
    ADDICTED,
    WEEKEND_WARRIOR,
    WIN_STREAK,
    WIN_STREAK_2,
    HAT_TRICK,
    REPEAT_OFFENDER,
    CLIMBER,
    HOLD_THE_LINE,
    COMEBACK,
    WIN_POOL,
    TOURIST,
    MAP_WIN,
    HOME_TURF,
    RACE_TOUR,
    MIRROR_MASTER,
    ANTI_RANDOM,
    SLAYER_HU,
    SLAYER_OC,
    SLAYER_NE,
    SLAYER_UD,
    FOUR_HORSEMEN,
    OFF_DUTY,
    NEMESIS,
    REVENGE,
    RIVAL,
    WIDE_NET,
    HUNTING_SEASON,
    OPEN_SEASON,
    CIVIL_WAR,
    GRAND_TOUR,
    SPEEDRUNNER,
    MARATHON,
    LADDER_GOAL_REACHED,
    DOUBLE_UP,
    CAPTAINS_DUTY,
    FIRST_TO_FIFTY,
]

TEAM_ACHIEVEMENTS = [
    FULL_ROSTER,
    EVERYONE_SCORES,
    HALF_REGULAR,
    EVERY_WEEK,
    NEVER_BLANK,
    FAST_START,
    NOBODY_LEFT,
    TEAM_NIGHT,
    TEAM_MAP_COVERAGE,
    TEAM_RACE_COVERAGE,
    TEAM_GRAND_TOUR,
    FIFTY_FACES,
    TEAM_GOAL,
    TWO_HUNDRED,
    TEAM_CLIMB,
    BRAGGING_RIGHTS,
    SPARRING_PARTNERS,
    EVERYONE_HUNTS,
]

# The race slayers, keyed by the race the opponent selected
SLAYERS = {"HU": SLAYER_HU, "OC": SLAYER_OC, "NE": SLAYER_NE, "UD": SLAYER_UD}

# The wc3.no set, as S17 and S18 ran it
WC3NO = [
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

# What S17 and S18 pay, row for row as production holds them. A season that ran
# under wc3.no keeps these exact prices; the reprice of 2026-09-06 is S19 onwards.
WC3NO_PAID: PaidSet = {
    "ladder_goal": 500,
    "double_up": 1000,
    "i_am_the_captain_now": 100,
    "addicted": 100,
    "elite": 100,
    "dats_fakt_ap": 50,
    "winner_winner": 50,
    "sad_trombone": 50,
    "win_streak_2": 50,
    "win_first": 15,
    "lose_first": 25,
    "win_streak": 25,
    "win_every_map": 25,
    "rising_star": 25,
    "falling_star": 25,
    "duck_hunting": 10,
    "night_elf": 10,
    "undead": 10,
    "orc": 10,
    "human": 10,
    "join_them": 10,
    "winter": 10,
    "holiday": 5,
    "newbie": 5,
}

# Every rule that ever paid: the wc3.no set, the S19 set and the team set. A rule
# dropped from a season keeps its code; the season simply has no price row for it.
ACHIEVEMENTS = (
    WC3NO + [rule for rule in S19_PLAYER if rule not in WC3NO] + TEAM_ACHIEVEMENTS
)
# The team badges, by id
TEAM_IDS = frozenset(rule.id for rule in TEAM_ACHIEVEMENTS)

# The rule pays for one race only, so the race the player beat most is looked
# up here. Random is in no bucket and pays nothing.
RACE_ACHIEVEMENTS = {"HU": HUMAN, "OC": ORC, "NE": NIGHT_ELF, "UD": UNDEAD}

# The w3champions race ids; the bundle gives a tie to the lowest of them
RACE_IDS = {"RANDOM": 0, "HU": 1, "OC": 2, "NE": 4, "UD": 8}


def total_points(found: Iterable[Achievement]) -> int:
    """What a player's achievements add to his ladder points."""
    return sum(item.points for item in found)


# What a season pays when nobody has changed it: the S19 player and team set at
# catalogue prices. A new season starts with exactly this; the seed loader writes
# it into every seeded season.
DEFAULT_PAID: PaidSet = {
    rule.id: rule.points for rule in S19_PLAYER + TEAM_ACHIEVEMENTS
}
# Every rule that ever paid, at catalogue prices; the tests seed a league with this
ALL_PAID: PaidSet = {rule.id: rule.points for rule in ACHIEVEMENTS}
