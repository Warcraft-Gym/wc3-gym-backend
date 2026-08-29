"""One test per achievement rule, at the boundary the rule turns on.

The rules are pure functions over a player's ordered matches, so most tests
craft rows and call core.achievements.earned directly. The two rules that
read a roster and the wiring into the routes are tested through the service.
"""

from collections.abc import Sequence
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from httpx2 import Client
from sqlalchemy import select
from sqlmodel import col

from app.core import achievements
from app.core.achievements import Achievement
from app.core.db import Session
from app.models.enums import Race
from app.models.team_season import DBTeamSeason
from app.models.w3c_ladder_match import W3CLadderMatch
from tests.test_ladder_read import INSIDE, add_match, ladder_of, player_of, sign_up
from tests.test_query_budget import count_statements

START = datetime(2026, 1, 7, 12, 0)


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
    ) -> None:
        self.won = won
        self.start_time = START + timedelta(minutes=minutes)
        self.duration_s = duration_s
        self.map_name = map_name
        self.opp_race = opp_race
        self.opp_battletag = opp_battletag
        self.mmr_before = mmr_before
        self.mmr_after = mmr_after


def run(
    rows: Sequence[achievements.AchievementRow], points: int = 0, **kwargs: object
) -> set[str]:
    """The ids of the rules these rows earn."""
    return {
        item.id
        for item in achievements.earned(
            rows, points, achievements.DEFAULT_PAID, **kwargs
        )
    }


def paid(
    rows: Sequence[achievements.AchievementRow], rule_id: str, **kwargs: object
) -> Achievement:
    """The earned rule itself, for the ones that pay a variable amount."""
    return next(
        item
        for item in achievements.earned(rows, 0, achievements.DEFAULT_PAID, **kwargs)
        if item.id == rule_id
    )


def series(results: list[bool]) -> list[Row]:
    """A run of matches, one a minute, in the order given."""
    return [Row(won=won, minutes=index) for index, won in enumerate(results)]


# The rules that read the match list alone.


def test_no_match_earns_nothing() -> None:
    assert achievements.earned([], 0, achievements.DEFAULT_PAID) == []


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
    late[0].start_time = datetime(2026, 1, 7, 23, 0)
    late[1].start_time = datetime(2026, 1, 8, 1, 0)
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


def test_i_am_the_captain_now_wants_a_win_over_a_coach() -> None:
    coaches = frozenset({"coach#1"})
    lost = [Row(won=False, opp_battletag="Coach#1")]
    assert "i_am_the_captain_now" not in run(lost, coaches=coaches)
    won = [Row(opp_battletag="Coach#1")]
    assert "i_am_the_captain_now" in run(won, coaches=coaches)


def test_a_coach_earns_nothing_for_beating_a_coach() -> None:
    won = [Row(opp_battletag="Coach#1")]
    coaches = frozenset({"coach#1", "me#1"})
    assert "i_am_the_captain_now" not in run(won, coaches=coaches, is_coach=True)


# The registry and the answer.


def test_every_rule_has_its_own_id_and_a_test() -> None:
    """The list is the whole rule set, so nothing ships untested."""
    ids = [rule.id for rule in achievements.ACHIEVEMENTS]
    assert len(ids) == len(set(ids)) == 24
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
    assert row["points"] == 3 + 15
    assert [badge["id"] for badge in row["achievements"]] == ["win_first"]
    assert row["achievements"][0] == {
        "id": "win_first",
        "points": 15,
        "name": "I am the danger!",
        "description": "Win your first GNL game",
        "icon": "mdi-redhat",
        "achieved_at": INSIDE.isoformat(),
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

    assert [badge["id"] for badge in row["achievements"]] == ["win_first", "win_streak"]


def test_the_roster_rules_read_the_season(
    client: Client, auth_headers: dict[str, str], league: dict[str, Any]
) -> None:
    """P1 on Alpha beats P3 on Beta, who coaches Beta."""
    one, three = league["player_ids"][0], league["player_ids"][2]
    with Session() as session:
        team_season = session.scalars(
            select(DBTeamSeason).where(col(DBTeamSeason.team_id) == league["team_b_id"])
        ).one()
        team_season.coach_1_id = three
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
    assert [badge["id"] for badge in body["achievements"]] == ["lose_first"]
    assert (body["ladder_points"], body["points"]) == (1, 26)


def test_the_badges_read_only_the_scoped_rows(
    client: Client, auth_headers: dict[str, str], league: dict[str, Any]
) -> None:
    """A short match, a match off the league race and a match outside the
    window are all invisible to the rules."""
    player = league["player_ids"][0]
    add_match(player, "short", won=True, duration_s=90, start_time=INSIDE)
    add_match(
        player,
        "other-race",
        won=True,
        race=Race.UD,
        start_time=INSIDE + timedelta(minutes=1),
    )
    add_match(player, "outside", won=True, start_time=datetime(2025, 12, 1, 12, 0))
    add_match(player, "counts", won=False, start_time=INSIDE + timedelta(minutes=2))

    row = player_of(ladder_of(client, auth_headers, league["season_id"]), player)

    assert [badge["id"] for badge in row["achievements"]] == ["lose_first"]


def test_the_rules_read_the_stored_rows(league: dict[str, Any]) -> None:
    """The Protocol the core declares is what the table actually holds."""
    player = league["player_ids"][0]
    add_match(player, "one", won=True)
    with Session() as session:
        rows = list(session.scalars(select(W3CLadderMatch)))
    assert run(rows) == {"win_first"}


def test_the_user_answer_costs_thirteen_statements(league: dict[str, Any]) -> None:
    """The count is a constant: it does not grow with the number of matches."""
    from app.services.ladder import LadderService

    player = league["player_ids"][0]
    for index in range(4):
        add_match(player, f"u{index}", start_time=INSIDE + timedelta(hours=index))

    with count_statements() as tally:
        answer = LadderService().user_ladder(player, league["season_id"])

    assert answer.games == 4
    assert tally[0] == 13


def test_a_badge_names_the_match_that_turned_its_rule_on() -> None:
    rows = series([True] * 4 + [False] + [True] * 5)
    at = {
        item.id: item.achieved_at
        for item in achievements.earned(rows, 500, achievements.DEFAULT_PAID)
    }
    assert at["win_first"] == rows[0].start_time
    # The streak completes on the tenth match, not the last one
    assert at["win_streak"] == rows[9].start_time
    # 3 a win, 1 a loss: the 168th match of the series carries the goal over 500
    long = series([True] * 200)
    goal = next(
        item
        for item in achievements.earned(long, 600, achievements.DEFAULT_PAID)
        if item.id == "ladder_goal"
    )
    assert goal.achieved_at == long[166].start_time
    # A catalogue entry has no date
    assert achievements.WIN_FIRST.achieved_at is None
