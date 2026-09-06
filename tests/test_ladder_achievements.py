"""One test per achievement rule, at the boundary the rule turns on.

The rules are one statement over the scoped matches, so most tests craft rows
and call the oracle of tests/achievement_oracle.py, which
tests/test_achievement_parity.py holds the statement to. The two rules that
read a roster and the wiring into the routes are tested through the service.
"""

from collections.abc import Sequence
from dataclasses import replace
from datetime import UTC, date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from httpx2 import Client
from sqlalchemy import select

from app.core import achievements
from app.core.achievement_rules import LIFETIME_FROM_W3C_SEASON
from app.core.achievements import Achievement
from app.core.db import Session
from app.models.enums import Race
from app.models.ladder_achievement import default_rows
from app.models.relationships import DBTeamSeasonCaptain
from app.models.w3c_ladder_match import W3CLadderMatch
from tests import achievement_oracle
from tests.test_ladder_read import INSIDE, add_match, ladder_of, player_of, sign_up
from tests.test_query_budget import count_statements

START = datetime(2026, 1, 7, 12, 0, tzinfo=UTC)


@pytest.fixture
def league(seeded: dict[str, Any], app: FastAPI) -> dict[str, Any]:
    """The seeded league with its four players signed up for the season."""
    sign_up(seeded["season_id"], seeded["player_ids"])
    return seeded


class Row:
    """One match as the rules read it."""

    def __init__(
        self,
        won: bool = True,
        minutes: int = 0,
        duration_s: int = 600,
        map_name: str = "Last Refuge",
        opp_race: Race | None = Race.HU,
        opp_battletag: str = "Someone#1234",
        mmr_before: int | None = 1500,
        mmr_after: int | None = 1512,
        race: Race | None = Race.HU,
        played_race: Race | None = Race.HU,
        opp_played_race: Race | None = None,
    ) -> None:
        self.won = won
        self.start_time = START + timedelta(minutes=minutes)
        self.duration_s = duration_s
        self.map_name = map_name
        self.race = race
        self.played_race = played_race
        self.opp_race = opp_race
        self.opp_played_race = opp_played_race
        self.opp_battletag = opp_battletag
        self.mmr_before = mmr_before
        self.mmr_after = mmr_after


def run(
    rows: Sequence[achievement_oracle.AchievementRow],
    points: int = 0,
    opponents: frozenset[str] = frozenset(),
    captains: frozenset[str] = frozenset(),
    is_captain: bool = False,
    season: achievement_oracle.Season | None = None,
) -> set[str]:
    """The ids of the rules these rows earn."""
    found = achievement_oracle.earned(
        rows, points, achievements.ALL_PAID, opponents, captains, is_captain, season
    )
    return {item.id for item in found}


def paid(
    rows: Sequence[achievement_oracle.AchievementRow],
    rule_id: str,
    opponents: frozenset[str] = frozenset(),
) -> Achievement:
    """The earned rule itself, for the ones that pay a variable amount."""
    found = achievement_oracle.earned(rows, 0, achievements.ALL_PAID, opponents)
    return next(item for item in found if item.id == rule_id)


def series(results: list[bool]) -> list[Row]:
    """A run of matches, one a minute, in the order given."""
    return [Row(won=won, minutes=index) for index, won in enumerate(results)]


# The rules that read the match list alone.


def test_no_match_earns_nothing() -> None:
    assert achievement_oracle.earned([], 0, achievements.ALL_PAID) == []


def test_win_first_and_lose_first_read_the_oldest_match() -> None:
    """Exactly one of the two is earned, and the oldest match decides."""
    assert "win_first" in run([Row(won=True, minutes=0), Row(won=False, minutes=1)])
    assert "lose_first" in run([Row(won=False, minutes=0), Row(won=True, minutes=1)])
    assert "lose_first" not in run([Row(won=True)])


def test_winner_winner_wants_a_hundred_wins() -> None:
    assert "winner_winner" not in run(series([True] * 99))
    assert "winner_winner" in run(series([True] * 100))


def test_sad_trombone_wants_a_hundred_losses() -> None:
    assert "sad_trombone" not in run(series([False] * 99))
    assert "sad_trombone" in run(series([False] * 100))


def test_elite_wants_the_mmr_hit_exactly() -> None:
    """1336 and 1338 do not pay; 1337 does, whether the match was won."""
    assert "elite" not in run([Row(mmr_after=1336), Row(minutes=1, mmr_after=1338)])
    assert "elite" in run([Row(mmr_after=1337)])


def test_dats_fakt_ap_wants_ten_losses_in_a_row() -> None:
    broken = [True] + [False] * 9 + [True] + [False] * 9
    assert "dats_fakt_ap" not in run(series(broken))
    assert "dats_fakt_ap" in run(series([True] + [False] * 10))


def test_win_streak_wants_five_in_a_row() -> None:
    """Four wins, a loss and four wins is no streak; five in a row is."""
    assert "win_streak" not in run(series([True] * 4 + [False] + [True] * 4))
    assert "win_streak" in run(series([True] * 5))


def test_win_streak_2_wants_ten_in_a_row() -> None:
    assert "win_streak_2" not in run(series([True] * 9 + [False] + [True] * 9))
    assert "win_streak_2" in run(series([True] * 10))


def test_join_them_wants_a_long_win_and_a_long_loss() -> None:
    """Over 30 minutes on both sides, not 30 minutes exactly."""
    exact = [Row(won=True, duration_s=1800), Row(won=False, minutes=1, duration_s=1800)]
    assert "join_them" not in run(exact)
    one_side = [Row(won=True, duration_s=1801), Row(won=False, minutes=1)]
    assert "join_them" not in run(one_side)
    both = [Row(won=True, duration_s=1801), Row(won=False, minutes=1, duration_s=1801)]
    assert "join_them" in run(both)


def test_addicted_wants_thirty_games_in_one_day() -> None:
    """29 in a day does not pay, and 29 plus one the next day does not either."""
    assert "addicted" not in run(series([True] * 29))
    spread = series([True] * 29) + [Row(minutes=24 * 60)]
    assert "addicted" not in run(spread)
    assert "addicted" in run(series([True] * 30))


def test_rising_star_wants_over_a_hundred_mmr_in_a_day() -> None:
    """The gains of one day are summed, and 100 exactly does not pay."""
    exact = [Row(minutes=i, mmr_before=1500, mmr_after=1550) for i in range(2)]
    assert "rising_star" not in run(exact)
    over = [Row(minutes=i, mmr_before=1500, mmr_after=1551) for i in range(2)]
    assert "rising_star" in run(over)


def test_falling_star_wants_over_a_hundred_mmr_lost_in_a_day() -> None:
    exact = [Row(minutes=i, mmr_before=1500, mmr_after=1450) for i in range(2)]
    assert "falling_star" not in run(exact)
    over = [Row(minutes=i, mmr_before=1500, mmr_after=1449) for i in range(2)]
    assert "falling_star" in run(over)


def test_a_day_is_a_calendar_day_not_a_rolling_window() -> None:
    """Two half days over one midnight are two days, as the bundle counts."""
    late = [Row(minutes=i, mmr_before=1500, mmr_after=1560) for i in range(2)]
    late[0].start_time = datetime(2026, 1, 7, 23, 0, tzinfo=UTC)
    late[1].start_time = datetime(2026, 1, 8, 1, 0, tzinfo=UTC)
    assert "rising_star" not in run(late)


def test_the_ladder_goal_and_double_up_read_the_ladder_points() -> None:
    rows = series([True])
    assert "ladder_goal" not in run(rows, points=499)
    assert "ladder_goal" in run(rows, points=500)
    assert "double_up" not in run(rows, points=999)
    assert "double_up" in run(rows, points=1000)


# The map rules.


def test_holiday_wants_a_win_on_tide_hunters() -> None:
    """A loss on the map does not count; only wins are read."""
    assert "holiday" not in run([Row(won=False, map_name="Tidehunters")])
    assert "holiday" in run([Row(map_name="Tidehunters")])


def test_winter_wants_a_win_on_every_winter_map() -> None:
    maps = list(achievements.WINTER_MAPS)
    assert "winter" not in run(
        [Row(minutes=i, map_name=name) for i, name in enumerate(maps[:-1])]
    )
    assert "winter" in run(
        [Row(minutes=i, map_name=name) for i, name in enumerate(maps)]
    )


def test_newbie_wants_a_win_on_every_new_map() -> None:
    maps = list(achievements.NEW_MAPS)
    assert "newbie" not in run(
        [Row(minutes=i, map_name=name) for i, name in enumerate(maps[:-1])]
    )
    assert "newbie" in run(
        [Row(minutes=i, map_name=name) for i, name in enumerate(maps)]
    )


def test_win_every_map_wants_a_win_on_the_whole_pool() -> None:
    maps = list(achievements.LADDER_MAPS)
    assert "win_every_map" not in run(
        [Row(minutes=i, map_name=name) for i, name in enumerate(maps[:-1])]
    )
    assert "win_every_map" in run(
        [Row(minutes=i, map_name=name) for i, name in enumerate(maps)]
    )


# The race rule: one race only, the one beaten most, above ten wins.


def test_the_race_rule_wants_more_than_ten_wins() -> None:
    ten = [Row(minutes=i, opp_race=Race.NE) for i in range(10)]
    assert "night_elf" not in run(ten)
    assert "night_elf" in run(ten + [Row(minutes=10, opp_race=Race.NE)])


def test_the_race_rule_pays_one_race_only() -> None:
    """Only the race beaten most often pays, however many others clear ten."""
    rows = [Row(minutes=i, opp_race=Race.NE) for i in range(12)]
    rows += [Row(minutes=100 + i, opp_race=Race.UD) for i in range(11)]
    earned = run(rows)
    assert "night_elf" in earned
    assert "undead" not in earned


def test_the_race_rule_pays_one_point_a_win() -> None:
    rows = [Row(minutes=i, opp_race=Race.OC) for i in range(14)]
    orc = paid(rows, "orc")
    assert orc.points == achievements.ORC.points + 14
    assert orc.description.endswith("14 wins!")


def test_a_tie_goes_to_the_lowest_w3champions_race_id() -> None:
    """Human is race 1 and Undead race 8, so a tie pays the human badge."""
    rows = [Row(minutes=i, opp_race=Race.HU) for i in range(12)]
    rows += [Row(minutes=100 + i, opp_race=Race.UD) for i in range(12)]
    earned = run(rows)
    assert "human" in earned
    assert "undead" not in earned


def test_beating_random_most_pays_no_race_badge() -> None:
    rows = [Row(minutes=i, opp_race=Race.RANDOM) for i in range(12)]
    assert run(rows) & {"human", "orc", "night_elf", "undead"} == set()


# The rules that read the season's rosters.


def test_duck_hunting_pays_five_a_kill() -> None:
    rows = [
        Row(minutes=0, opp_battletag="Foe#1"),
        Row(minutes=1, opp_battletag="Foe#2"),
        Row(minutes=2, won=False, opp_battletag="Foe#3"),
        Row(minutes=3, opp_battletag="Stranger#9"),
    ]
    foes = frozenset({"foe#1", "foe#2", "foe#3"})
    assert "duck_hunting" not in run(rows, opponents=frozenset())
    hunt = paid(rows, "duck_hunting", opponents=foes)
    # Two wins over the foes; the loss to Foe#3 pays nothing
    assert hunt.points == achievements.DUCK_HUNTING.points + 10
    assert hunt.description.endswith("2 kill(s)")


def test_i_am_the_captain_now_wants_a_win_over_a_captain() -> None:
    captains = frozenset({"captain#1"})
    lost = [Row(won=False, opp_battletag="Captain#1")]
    assert "i_am_the_captain_now" not in run(lost, captains=captains)
    won = [Row(opp_battletag="Captain#1")]
    assert "i_am_the_captain_now" in run(won, captains=captains)


def test_a_captain_earns_nothing_for_beating_a_captain() -> None:
    won = [Row(opp_battletag="Captain#1")]
    captains = frozenset({"captain#1", "me#1"})
    assert "i_am_the_captain_now" not in run(won, captains=captains, is_captain=True)


# The registry and the answer.


def test_every_rule_has_its_own_id_and_a_test() -> None:
    """The list is the whole rule set, so nothing ships untested."""
    ids = [rule.id for rule in achievements.ACHIEVEMENTS]
    assert len(ids) == len(set(ids)) == 91
    tested = Path(__file__).read_text()
    for rule_id in ids:
        assert f'"{rule_id}"' in tested, rule_id


def test_the_answer_carries_the_badges_and_adds_their_points(
    client: Client, auth_headers: dict[str, str], league: dict[str, Any]
) -> None:
    """points is ladder points plus achievement points; ladder_points is not."""
    player = league["player_ids"][0]
    add_match(player, "first", won=True, start_time=INSIDE)

    row = player_of(ladder_of(client, auth_headers, league["season_id"]), player)

    assert row["ladder_points"] == 3
    # The first win and, on the third day of the season, the early bird
    assert row["points"] == 3 + 3 + 3
    assert [badge["id"] for badge in row["achievements"]] == ["win_first", "early_bird"]
    assert row["achievements"][0] == {
        "id": "win_first",
        "points": 3,
        "name": "I am the danger!",
        "description": "Win your first game",
        "icon": "mdi-redhat",
        "achieved_at": INSIDE.isoformat().replace("+00:00", "Z"),
    }


def test_the_badges_come_oldest_first(
    client: Client, auth_headers: dict[str, str], league: dict[str, Any]
) -> None:
    player = league["player_ids"][0]
    for index in range(5):
        add_match(
            player, f"w{index}", won=True, start_time=INSIDE + timedelta(minutes=index)
        )

    row = player_of(ladder_of(client, auth_headers, league["season_id"]), player)

    # Five mirror wins a minute apart over one opponent: the first and the
    # early bird, the hat-trick, three wins in an hour and the nemesis on the
    # third, then the streak, the sitting, the mirrors, the rival and the first
    # week's five games all on the fifth, in the order the rules are evaluated
    assert [badge["id"] for badge in row["achievements"]] == [
        "win_first",
        "early_bird",
        "hat_trick",
        "power_hour",
        "nemesis",
        "win_streak",
        "one_sitting",
        "mirror_master",
        "rival",
        "week_one",
    ]


def test_the_roster_rules_read_the_season(
    client: Client, auth_headers: dict[str, str], league: dict[str, Any]
) -> None:
    """P1 on Alpha beats P3 on Beta, who captains Beta."""
    one, three = league["player_ids"][0], league["player_ids"][2]
    with Session() as session:
        session.add(
            DBTeamSeasonCaptain(
                team_id=league["team_b_id"],
                season_id=league["season_id"],
                user_id=three,
            )
        )
        session.commit()
    add_match(one, "kill", won=True, opp_battletag="P3#3333")

    row = player_of(ladder_of(client, auth_headers, league["season_id"]), one)

    badges = {badge["id"]: badge for badge in row["achievements"]}
    assert badges["duck_hunting"]["points"] == 15
    assert "i_am_the_captain_now" in badges


def test_a_teammate_is_no_duck(
    client: Client, auth_headers: dict[str, str], league: dict[str, Any]
) -> None:
    one = league["player_ids"][0]
    add_match(one, "mate", won=True, opp_battletag="P2#2222")

    row = player_of(ladder_of(client, auth_headers, league["season_id"]), one)

    assert "duck_hunting" not in {badge["id"] for badge in row["achievements"]}


def test_the_user_route_answers_the_badges_too(
    client: Client, auth_headers: dict[str, str], league: dict[str, Any]
) -> None:
    player = league["player_ids"][0]
    add_match(player, "first", won=False, start_time=INSIDE)

    resp = client.get(
        f"/users/{player}/ladder?season_id={league['season_id']}", headers=auth_headers
    )

    assert resp.status_code == 200
    body = resp.json()
    assert [badge["id"] for badge in body["achievements"]] == [
        "lose_first",
        "early_bird",
    ]
    assert (body["ladder_points"], body["points"]) == (1, 1 + 5 + 3)


def test_the_badges_read_only_the_scoped_rows(
    client: Client, auth_headers: dict[str, str], league: dict[str, Any]
) -> None:
    """A short match and a match outside the window are invisible to the
    rules. A match off the league race is read by the two off-race rules and
    by no other."""
    player = league["player_ids"][0]
    add_match(player, "short", won=True, duration_s=90, start_time=INSIDE)
    add_match(
        player,
        "other-race",
        won=True,
        race=Race.UD,
        start_time=INSIDE + timedelta(minutes=1),
    )
    add_match(
        player, "outside", won=True, start_time=datetime(2025, 12, 1, 12, 0, tzinfo=UTC)
    )
    add_match(player, "counts", won=False, start_time=INSIDE + timedelta(minutes=2))

    row = player_of(ladder_of(client, auth_headers, league["season_id"]), player)

    assert {badge["id"] for badge in row["achievements"]} == {
        "off_duty",
        "lose_first",
        "early_bird",
    }


def test_the_lifetime_badges_start_at_a_w3champions_season(
    client: Client, auth_headers: dict[str, str], league: dict[str, Any]
) -> None:
    """The scope that spans seasons reads the seasons from the cutoff on."""
    player = league["player_ids"][0]
    with Session() as session:
        session.add_all(default_rows(None))
        session.commit()
    add_match(player, "before", won=True, wc3_season=LIFETIME_FROM_W3C_SEASON - 1)

    body = client.get(f"/users/{player}/ladder", headers=auth_headers).json()
    assert body["achievements"] == []

    add_match(
        player,
        "after",
        won=True,
        wc3_season=LIFETIME_FROM_W3C_SEASON,
        start_time=INSIDE + timedelta(minutes=1),
    )

    body = client.get(f"/users/{player}/ladder", headers=auth_headers).json()
    assert [badge["id"] for badge in body["achievements"]] == ["win_first"]


def test_the_rules_read_the_stored_rows(league: dict[str, Any]) -> None:
    """The Protocol the oracle declares is what the table actually holds."""
    player = league["player_ids"][0]
    add_match(player, "one", won=True)
    with Session() as session:
        rows = list(session.scalars(select(W3CLadderMatch)))
    assert run(rows) == {"win_first"}


def test_the_user_answer_costs_a_constant_number_of_statements(
    league: dict[str, Any],
) -> None:
    """The count is a constant: it does not grow with the number of matches.
    Fourteen: the thirteen of the user answer and the map pool."""
    from app.services.ladder import LadderService

    player = league["player_ids"][0]
    for index in range(4):
        add_match(player, f"u{index}", start_time=INSIDE + timedelta(hours=index))

    with count_statements() as tally:
        answer = LadderService().user_ladder(player, league["season_id"])

    assert answer.games == 4
    assert tally[0] == 14


def test_a_badge_names_the_match_that_turned_its_rule_on() -> None:
    rows = series([True] * 4 + [False] + [True] * 5)
    at = {
        item.id: item.achieved_at
        for item in achievement_oracle.earned(rows, 500, achievements.ALL_PAID)
    }
    assert at["win_first"] == rows[0].start_time
    # The streak completes on the tenth match, not the last one
    assert at["win_streak"] == rows[9].start_time
    # 3 a win, 1 a loss: the 168th match of the series carries the goal over 500
    long = series([True] * 200)
    goal = next(
        item
        for item in achievement_oracle.earned(long, 600, achievements.ALL_PAID)
        if item.id == "ladder_goal"
    )
    assert goal.achieved_at == long[166].start_time
    # A catalogue entry has no date
    assert achievements.WIN_FIRST.achieved_at is None


def test_deleting_a_season_drops_its_prices(seeded: dict[str, Any]) -> None:
    from sqlmodel import col

    from app.api.deps import season_service
    from app.models.ladder_achievement import LadderAchievement

    season_service.delete(seeded["season_id"])
    with Session() as session:
        rows = session.scalars(
            select(LadderAchievement).where(
                col(LadderAchievement.season_id) == seeded["season_id"]
            )
        ).all()
        assert rows == []


# The S19 rules, each at the boundary it turns on, against the oracle.

WINDOW = (
    datetime(2026, 1, 5, 0, 0, tzinfo=UTC),
    datetime(2026, 2, 27, 23, 59, 59, 999999, tzinfo=UTC),
)
DAY = 24 * 60
POOL = ("Last Refuge", "Tidehunters")
FOES = frozenset({"foe#1", "foe#2"})
MATES = frozenset({"mate#1"})
MEMBERS = FOES | MATES | {"x#1", "y#1", "z#1"}
SEASON = achievement_oracle.Season(
    window=WINDOW,
    pool=POOL,
    opponents=FOES,
    teammates=MATES,
    members=MEMBERS,
    team_of_tag={"foe#1": 2, "foe#2": 2, "x#1": 3, "mate#1": 1},
    own_team=1,
    teams=3,
    league_race="HU",
)


def days(count: int, step_days: int = 1, **kw: Any) -> list[Row]:  # noqa: ANN401
    """One match a day, `step_days` apart, from START on."""
    return [Row(minutes=index * step_days * DAY, **kw) for index in range(count)]


def busy_days(count: int, per_day: int) -> list[Row]:
    return [Row(minutes=d * DAY + m) for d in range(count) for m in range(per_day)]


def versus(tags: Sequence[str], won: bool = True) -> list[Row]:
    return [Row(won=won, minutes=i, opp_battletag=tag) for i, tag in enumerate(tags)]


def _saturdays(count: int) -> list[Row]:
    # 2026-01-10 is the first Saturday after START (Wednesday 2026-01-07)
    return [Row(minutes=(3 + 7 * week) * DAY) for week in range(count)]


S19_CASES: dict[str, tuple[list[Row], dict[str, Any]]] = {
    "early_bird": ([Row()], {}),
    "week_one": (series([True] * 5), {}),
    "last_call": ([Row(minutes=50 * DAY)], {}),  # 2026-02-26
    "games_25": (series([True] * 25), {}),
    "games_50": (series([True] * 50), {}),
    "games_100": (series([True] * 100), {}),
    "plus_twenty": (series([True] * 20), {}),
    "twenty_hours": (series([True] * 120), {}),  # 120 games of 600 s
    "streak_week": (days(7), {}),
    "twenty_days": (days(20), {}),
    "five_a_day": (busy_days(10, 5), {}),
    "always_here": (days(8, step_days=7), {}),
    "weekly_regular": (
        busy_days(4 * 7, 1)
        + [Row(minutes=w * 7 * DAY + m) for w in range(4) for m in range(1, 5)],
        {},
    ),
    "month_of_sundays": (_saturdays(4), {}),
    "never_gone": (days(26, step_days=2), {}),
    "welcome_back": ([Row(), Row(minutes=14 * DAY)], {}),
    "one_sitting": (series([True] * 5), {}),
    "power_hour": (series([True] * 3), {}),
    "weekend_warrior": ([Row(minutes=3 * DAY + m) for m in range(10)], {}),
    "hat_trick": (series([True] * 3), {}),
    "repeat_offender": (series([True, True, True, False] * 3), {}),
    "climber": ([Row(mmr_before=1500, mmr_after=1600)], {}),
    "hold_the_line": (series([True] * 30), {}),  # every match 1500 to 1512
    "comeback": (
        [Row(mmr_before=1500, mmr_after=1400)]
        + [Row(minutes=i, mmr_before=1400, mmr_after=1500) for i in range(1, 30)],
        {},
    ),
    "win_pool": ([Row(map_name=m, minutes=i) for i, m in enumerate(POOL)], {}),
    "tourist": (
        [Row(won=False, map_name=m, minutes=i) for i, m in enumerate(POOL)],
        {},
    ),
    "home_turf": (series([True] * 10), {}),
    "race_tour": (
        [
            Row(opp_race=r, minutes=i)
            for i, r in enumerate((Race.HU, Race.OC, Race.NE, Race.UD))
        ],
        {},
    ),
    "mirror_master": ([Row(minutes=i, opp_played_race=Race.HU) for i in range(5)], {}),
    "anti_random": ([Row(minutes=i, opp_race=Race.RANDOM) for i in range(5)], {}),
    "slayer_hu": (series([True] * 7 + [False] * 3), {}),
    "slayer_oc": ([Row(won=i < 7, minutes=i, opp_race=Race.OC) for i in range(10)], {}),
    "slayer_ne": ([Row(won=i < 7, minutes=i, opp_race=Race.NE) for i in range(10)], {}),
    "slayer_ud": ([Row(won=i < 7, minutes=i, opp_race=Race.UD) for i in range(10)], {}),
    "nemesis": (versus(["foe#9"] * 3), {}),
    "revenge": (
        versus(["foe#9"], won=False) + [Row(minutes=1, opp_battletag="foe#9")],
        {},
    ),
    "rival": (versus(["foe#9"] * 5, won=False), {}),
    "wide_net": (versus([f"o{i}#1" for i in range(20)]), {}),
    "hunting_season": (versus(["foe#1"]), {}),
    "open_season": (versus(sorted(MEMBERS)), {}),
    "civil_war": (versus(["mate#1"]), {}),
    "grand_tour": (versus(["foe#1", "x#1"]), {}),
    "speedrunner": ([Row(duration_s=420)], {}),
    "marathon": ([Row(won=False, duration_s=2700)], {}),
    "captains_duty": (series([True] * 20), {"is_captain": True}),
    "first_to_fifty": (
        series([True] * 50),
        {"season": replace(SEASON, is_first_to_fifty=True)},
    ),
    "four_horsemen": (
        [],
        {
            "season": replace(
                SEASON,
                all_rows=[
                    Row(played_race=r, minutes=i)
                    for i, r in enumerate((Race.HU, Race.OC, Race.NE, Race.UD))
                ],
            )
        },
    ),
    "off_duty": (
        [],
        {"season": replace(SEASON, all_rows=[Row(race=Race.OC, played_race=Race.OC)])},
    ),
}


@pytest.mark.parametrize("rule_id", sorted(S19_CASES))
def test_the_s19_rule_turns_on_at_its_boundary(rule_id: str) -> None:
    rows, options = S19_CASES[rule_id]
    season = options.pop("season", SEASON)
    assert rule_id in run(rows, season=season, **options)


@pytest.mark.parametrize(
    ("rule_id", "rows"),
    [
        ("week_one", series([True] * 4)),
        ("games_25", series([True] * 24)),
        ("plus_twenty", series([True] * 19)),
        ("streak_week", days(6) + [Row(minutes=7 * DAY)]),
        ("five_a_day", busy_days(10, 4)),
        ("welcome_back", [Row(), Row(minutes=14 * DAY - 1)]),
        ("one_sitting", [Row(minutes=m) for m in (0, 1, 2, 3, 181)]),
        ("repeat_offender", series([True, True, True, False] * 2 + [True, True])),
        ("climber", [Row(mmr_before=1500, mmr_after=1599)]),
        ("hold_the_line", series([True] * 29)),
        (
            "comeback",
            [Row(mmr_before=1500, mmr_after=1400)]
            + [Row(minutes=i, mmr_before=1400, mmr_after=1499) for i in range(1, 30)],
        ),
        ("hat_trick", series([True, True, False, True, True])),
        (
            "revenge",
            [
                Row(opp_battletag="foe#9"),
                Row(won=False, minutes=1, opp_battletag="foe#9"),
            ],
        ),
        ("mirror_master", [Row(minutes=i, opp_played_race=Race.OC) for i in range(5)]),
        ("slayer_hu", series([True] * 6 + [False] * 4)),
        ("nemesis", versus(["foe#9"] * 2 + ["foe#8"])),
        ("wide_net", versus([f"o{i}#1" for i in range(19)] + ["o0#1"])),
        ("grand_tour", versus(["foe#1", "foe#2"])),  # the same other team twice
        ("speedrunner", [Row(duration_s=421)]),
        ("marathon", [Row(duration_s=2699)]),
        ("captains_duty", series([True] * 20)),  # not a captain
    ],
)
def test_the_s19_rule_stays_off_short_of_its_boundary(
    rule_id: str, rows: list[Row]
) -> None:
    assert rule_id not in run(rows, season=SEASON)


def test_map_win_pays_one_badge_per_map_of_the_pool() -> None:
    earned = run([Row(map_name="Tidehunters")], season=SEASON)
    assert "map_win:Tidehunters" in earned
    assert "map_win:Last Refuge" not in earned
    assert "map_win" not in earned


def test_the_off_race_rules_read_no_league_race_match() -> None:
    """A win on the league race is no off-duty win."""
    season = replace(SEASON, all_rows=[Row(race=Race.HU, played_race=Race.HU)])
    assert "off_duty" not in run([], season=season)


def test_the_window_rules_are_skipped_over_a_lifetime() -> None:
    """No window means no first week and no last call."""
    found = run(days(8, step_days=7), season=replace(SEASON, window=None))
    assert not found & {
        "early_bird",
        "week_one",
        "last_call",
        "always_here",
        "never_gone",
    }


# The team rules: the folds over per-player numbers, and the SQL ones through
# the season route.


def _team_fold(
    users: list[int],
    totals: dict[int, Any] | None = None,
    spans: dict[int, Any] | None = None,
    days_of: dict[int, list[Any]] | None = None,
    races: dict[int, dict[str, list[int]]] | None = None,
    badges: dict[int, list[Achievement]] | None = None,
) -> set[str]:
    totals, spans, races, badges = totals or {}, spans or {}, races or {}, badges or {}
    days_of = days_of or {}
    from types import SimpleNamespace

    from app.core import team_achievements
    from app.core.achievement_rules import Context

    ctx = Context(window=WINDOW, teams={1: users}, tags={1: [f"p{u}#1" for u in users]})
    found: dict[int, list[Achievement]] = {}

    def pay(team: int, rule: Achievement, at: datetime | None) -> None:
        found.setdefault(team, []).append(replace(rule, achieved_at=at))

    team_achievements._fold(
        pay,
        1,
        users,
        ctx,
        {u: SimpleNamespace(**t) for u, t in totals.items()},
        {u: SimpleNamespace(**t) for u, t in spans.items()},
        {u: [SimpleNamespace(**d) for d in rows] for u, rows in days_of.items()},
        races,
        badges,
    )
    return {badge.id for badge in found.get(1, [])}


def _total(games: int, wins: int = 0, points: int = 0) -> dict[str, int]:
    return {"games": games, "wins": wins, "points": points}


def _day(day: date, wins: int = 0, losses: int = 0) -> dict[str, Any]:
    return {"day": day, "wins": wins, "losses": losses}


def test_full_roster_wants_every_player_on_ten_games() -> None:
    assert "full_roster" in _team_fold([1, 2], {1: _total(10), 2: _total(10)})
    assert "full_roster" not in _team_fold([1, 2], {1: _total(10), 2: _total(9)})
    assert "full_roster" not in _team_fold([1, 2], {1: _total(10)})


def test_everyone_scores_wants_a_win_each() -> None:
    assert "everyone_scores" in _team_fold([1, 2], {1: _total(1, 1), 2: _total(1, 1)})
    assert "everyone_scores" not in _team_fold(
        [1, 2], {1: _total(1, 1), 2: _total(1, 0)}
    )


def test_half_regular_folds_the_weekly_regular_badges() -> None:
    badge = replace(achievements.WEEKLY_REGULAR, achieved_at=START)
    assert "half_regular" in _team_fold([1, 2, 3], badges={1: [badge], 2: [badge]})
    assert "half_regular" not in _team_fold([1, 2, 3], badges={1: [badge]})


def test_everyone_hunts_folds_the_hunting_badges() -> None:
    badge = replace(achievements.HUNTING_SEASON, achieved_at=START)
    assert "everyone_hunts" in _team_fold([1, 2], badges={1: [badge], 2: [badge]})
    assert "everyone_hunts" not in _team_fold([1, 2], badges={1: [badge]})


def test_the_capped_sums_count_at_most_the_cap_per_player() -> None:
    # 150 of 900 points count, so seven such players reach 1000 and six do not
    heavy = {u: _total(300, 300, 900) for u in range(7)}
    assert "team_goal" in _team_fold(list(heavy), heavy)
    assert "team_goal" not in _team_fold(
        list(range(6)), {u: heavy[u] for u in range(6)}
    )
    # 30 of 300 games count, so seven players reach 200 and six do not
    assert "two_hundred" in _team_fold(list(heavy), heavy)
    assert "two_hundred" not in _team_fold(
        list(range(6)), {u: heavy[u] for u in range(6)}
    )
    # 100 of 400 MMR count, so five players reach 500 and four do not
    climbs = {u: {"start": 1000, "current": 1400} for u in range(5)}
    assert "team_climb" in _team_fold(list(climbs), spans=climbs)
    assert "team_climb" not in _team_fold(
        list(range(4)), spans={u: climbs[u] for u in range(4)}
    )


def test_team_race_coverage_unions_the_races_the_players_beat() -> None:
    races = {1: {"HU": [1, 0], "OC": [1, 0]}, 2: {"NE": [1, 0], "UD": [1, 0]}}
    assert "team_race_coverage" in _team_fold([1, 2], races=races)
    races[2]["UD"] = [0, 1]
    assert "team_race_coverage" not in _team_fold([1, 2], races=races)


def test_the_week_folds_read_every_week_of_the_window() -> None:
    weeks = [date(2026, 1, 5) + timedelta(days=7 * w) for w in range(8)]
    # three players with three games in every week, one of them winning
    days_of = {
        u: [
            _day(week, wins=1 if u == 1 else 0, losses=2 if u == 1 else 3)
            for week in weeks
        ]
        for u in (1, 2, 3)
    }
    found = _team_fold([1, 2, 3], days_of=days_of)
    assert {"every_week", "never_blank", "fast_start", "nobody_left"} <= found
    # one week short of a third player, and no win in it
    days_of[3] = days_of[3][1:]
    days_of[1][0] = _day(weeks[0], wins=0, losses=3)
    found = _team_fold([1, 2, 3], days_of=days_of)
    assert not found & {"every_week", "never_blank", "fast_start"}
    assert "nobody_left" in found


def test_team_night_wants_thirty_games_from_five_players_in_one_day() -> None:
    night = {u: [_day(date(2026, 1, 10), wins=3, losses=3)] for u in range(5)}
    assert "team_night" in _team_fold(list(night), days_of=night)
    assert "team_night" not in _team_fold(
        list(range(4)), days_of={u: night[u] for u in range(4)}
    )


def test_the_sql_team_rules_read_the_roster_matches(
    client: Client, auth_headers: dict[str, str], league: dict[str, Any]
) -> None:
    """Alpha (P1, P2) beats Beta (P3, P4) twenty times, wins the one map of
    the pool, spars ten times and beats fifty different opponents."""
    one, two = league["player_ids"][:2]
    for index in range(20):
        add_match(
            one,
            f"beta{index}",
            won=True,
            opp_battletag="P3#3333",
            start_time=INSIDE + timedelta(minutes=index),
        )
    for index in range(10):
        add_match(
            two,
            f"spar{index}",
            won=False,
            opp_battletag="P1#1111",
            start_time=INSIDE + timedelta(hours=1, minutes=index),
        )
    for index in range(50):
        add_match(
            one,
            f"face{index}",
            won=True,
            opp_battletag=f"Face{index}#1",
            start_time=INSIDE + timedelta(hours=2, minutes=index),
            map_name="Concealed Hill",
        )

    body = ladder_of(client, auth_headers, league["season_id"])
    alpha = next(team for team in body["teams"] if team["id"] == league["team_a_id"])
    beta = next(team for team in body["teams"] if team["id"] == league["team_b_id"])

    assert {badge["id"] for badge in alpha["achievements"]} >= {
        "team_map_coverage",
        "team_grand_tour",
        "bragging_rights",
        "sparring_partners",
        "fifty_faces",
    }
    assert "team_grand_tour" not in {badge["id"] for badge in beta["achievements"]}
    assert [rule["id"] for rule in body["team_achievement_rules"]] == [
        rule.id for rule in achievements.TEAM_ACHIEVEMENTS
    ]
