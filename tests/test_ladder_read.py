"""The ladder read path: one rule, two faces, and answers aggregated in SQL.

Every number in a ladder answer is a group the database computed over
w3c_ladder_matches. Nothing is stored, so the tests write matches and read
the routes.

The scope of every answer is the same: matches longer than
core.ladder.MIN_DURATION_S, of the players asked for, inside the window
asked for.
"""

import importlib.util
from dataclasses import asdict
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from fastapi import FastAPI
from httpx2 import Client
from sqlalchemy import case, func, select
from sqlmodel import col

from app.core import ladder
from app.core.achievements import ACHIEVEMENTS
from app.core.db import Session
from app.models.enums import Race
from app.models.ladder_achievement import LadderAchievement, default_rows
from app.models.ladder_sync import LadderSync
from app.models.relationships import DBUserSeasonSignup
from app.models.season import Season
from app.models.user import User
from app.models.w3c_ladder_match import W3CLadderMatch
from tests.test_query_budget import count_statements

# The seeded season runs 2026-01-05 to 2026-02-27.
INSIDE = datetime(2026, 1, 7, 14, 30)


def sign_up(season_id: int, user_ids: list[int], race: Race | None = None) -> None:
    with Session() as session:
        for user_id in user_ids:
            session.add(
                DBUserSeasonSignup(user_id=user_id, season_id=season_id, race=race)
            )
        session.commit()


def set_signup_race(season_id: int, user_id: int, race: Race) -> None:
    """The race the player registered on for that one season."""
    with Session() as session:
        key = {"season_id": season_id, "user_id": user_id}
        session.get(DBUserSeasonSignup, key).race = race
        session.commit()


def second_season(season_id: int) -> int:
    """Another season over the same days, so only the signup race differs."""
    with Session() as session:
        first = session.get_one(Season, season_id)
        other = Season(
            name="Signup fallback",
            number_weeks=first.number_weeks,
            series_per_week=first.series_per_week,
            start_date=first.start_date,
            end_date=first.end_date,
        )
        session.add(other)
        session.flush()
        session.add_all(default_rows(other.id))
        session.commit()
        assert other.id is not None
        return other.id


def add_match(
    user_id: int,
    match_id: str,
    start_time: datetime = INSIDE,
    wc3_season: int = 25,
    duration_s: int = 600,
    won: bool = True,
    opp_race: Race = Race.HU,
    mmr_before: int | None = 1500,
    mmr_after: int | None = 1512,
    opp_battletag: str = "Someone#1234",
    race: Race | None = None,
    played_race: Race | None = None,
    opp_played_race: Race | None = None,
) -> None:
    """One stored match. Without a race it is selected on the league race,
    and without a played race each side played the race it selected."""
    with Session() as session:
        session.add(
            W3CLadderMatch(
                w3c_match_id=match_id,
                user_id=user_id,
                wc3_season=wc3_season,
                start_time=start_time,
                duration_s=duration_s,
                map_name="Last Refuge",
                race=race or session.get_one(User, user_id).race,
                played_race=played_race or race or session.get_one(User, user_id).race,
                opp_battletag=opp_battletag,
                opp_race=opp_race,
                opp_played_race=opp_played_race or opp_race,
                won=won,
                mmr_before=mmr_before,
                mmr_after=mmr_after,
            )
        )
        session.commit()


def stamp_ladder(user_id: int, wc3_season: int, synced_at: datetime) -> None:
    """One ladder sync ledger row, as a finished sync leaves it."""
    with Session() as session:
        session.add(
            LadderSync(
                user_id=user_id,
                wc3_season=wc3_season,
                synced_at=synced_at,
                complete=True,
            )
        )
        session.commit()


def matches_of(
    client: Client, headers: dict[str, str], user_id: int, season_id: int
) -> list[str]:
    """The match ids one player scored in a season, newest first."""
    resp = client.get(f"/users/{user_id}/ladder?season_id={season_id}", headers=headers)
    assert resp.status_code == 200, resp.text
    return [match["w3c_match_id"] for match in resp.json()["matches"]]


@pytest.fixture
def league(seeded: dict[str, Any]) -> dict[str, Any]:
    """The seeded league with its four players signed up for the season."""
    sign_up(seeded["season_id"], seeded["player_ids"])
    return seeded


def ladder_of(
    client: Client, headers: dict[str, str], season_id: int
) -> dict[str, Any]:
    resp = client.get(f"/seasons/{season_id}/ladder", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def player_of(body: dict[str, Any], user_id: int) -> dict[str, Any]:
    return next(
        player
        for team in body["teams"]
        for player in team["players"]
        if player["id"] == user_id
    )


# The rule.


def test_the_two_faces_of_the_rule_agree(app: FastAPI, league: dict[str, Any]) -> None:
    """Over every duration around the boundary, SQL pays what Python pays."""
    player = league["player_ids"][0]
    durations = [0, 1, 60, 119, 120, 121, 122, 600, 3600]
    for index, duration in enumerate(durations):
        for won in (True, False):
            add_match(
                player,
                f"m{index}{int(won)}",
                duration_s=duration,
                won=won,
                start_time=INSIDE + timedelta(minutes=index),
            )

    with Session() as session:
        rows = list(session.scalars(select(W3CLadderMatch)))
        in_sql = session.execute(
            select(
                col(W3CLadderMatch.id),
                ladder.points_case(
                    col(W3CLadderMatch.won), col(W3CLadderMatch.duration_s)
                ),
                case(
                    (ladder.counted_clause(col(W3CLadderMatch.duration_s)), 1), else_=0
                ),
            )
        ).all()
        totals = session.execute(
            select(
                func.sum(
                    ladder.points_case(
                        col(W3CLadderMatch.won), col(W3CLadderMatch.duration_s)
                    )
                ),
                func.sum(
                    case(
                        (ladder.counted_clause(col(W3CLadderMatch.duration_s)), 1),
                        else_=0,
                    )
                ),
            )
        ).one()

    by_id = {row.id: row for row in rows}
    for row_id, points, counted in in_sql:
        row = by_id[row_id]
        assert points == ladder.points(row.won, row.duration_s), row.duration_s
        assert bool(counted) is ladder.counted(row.duration_s), row.duration_s

    in_python = ladder.totals(rows)
    assert totals == (in_python.points, in_python.games)
    # The boundary itself: 120 s pays nothing, 121 s pays
    assert ladder.points(True, 120) == 0
    assert ladder.points(False, 120) == 0
    assert ladder.points(True, 121) == ladder.WIN_POINTS
    assert ladder.points(False, 121) == ladder.LOSS_POINTS


def test_a_short_match_is_no_game(
    client: Client, auth_headers: dict[str, str], league: dict[str, Any]
) -> None:
    """A 120 s match is not counted; a 121 s one is."""
    player = league["player_ids"][0]
    add_match(player, "short", duration_s=120)
    add_match(player, "long", duration_s=121, start_time=INSIDE + timedelta(hours=1))

    body = ladder_of(client, auth_headers, league["season_id"])

    assert body["total_games"] == 1
    row = player_of(body, player)
    assert (row["games"], row["wins"], row["ladder_points"]) == (1, 1, 3)


# The season window.


def test_the_window_takes_the_season_and_nothing_around_it(
    client: Client, auth_headers: dict[str, str], league: dict[str, Any]
) -> None:
    """One second before the start and one second after the end are out."""
    player = league["player_ids"][0]
    add_match(player, "before", start_time=datetime(2026, 1, 4, 23, 59, 59))
    add_match(player, "first", start_time=datetime(2026, 1, 5, 0, 0, 0))
    add_match(player, "last", start_time=datetime(2026, 2, 27, 23, 59, 59))
    add_match(player, "after", start_time=datetime(2026, 2, 28, 0, 0, 0))

    body = ladder_of(client, auth_headers, league["season_id"])

    assert body["total_games"] == 2
    assert player_of(body, player)["games"] == 2
    assert body["season"]["start_date"] == "2026-01-05"
    assert body["season"]["end_date"] == "2026-02-27"


def test_a_player_with_no_matches_reads_zeros(
    client: Client, auth_headers: dict[str, str], league: dict[str, Any]
) -> None:
    """Signed up and never played is a row of zeros, not a missing row."""
    body = ladder_of(client, auth_headers, league["season_id"])

    assert [player["id"] for team in body["teams"] for player in team["players"]] != []
    row = player_of(body, league["player_ids"][0])
    assert (row["points"], row["wins"], row["losses"], row["games"]) == (0, 0, 0, 0)
    assert row["per_day"] == []
    assert row["mmr"] == {"start": None, "min": None, "max": None, "current": None}
    assert row["vs_race"] == {race.value: [0, 0] for race in Race}
    assert row["achievements"] == []


def test_a_match_between_two_gnl_players_counts_once_in_the_season(
    client: Client, auth_headers: dict[str, str], league: dict[str, Any]
) -> None:
    """Both players own their own row; the season total counts the match once."""
    one, two = league["player_ids"][0], league["player_ids"][2]
    add_match(one, "shared", won=True)
    add_match(two, "shared", won=False)

    body = ladder_of(client, auth_headers, league["season_id"])

    assert body["total_games"] == 1
    assert player_of(body, one)["games"] == 1
    assert player_of(body, two)["games"] == 1
    assert sum(team["games"] for team in body["teams"]) == 2


def test_the_teams_carry_the_points_of_their_players(
    client: Client, auth_headers: dict[str, str], league: dict[str, Any]
) -> None:
    one, two = league["player_ids"][0], league["player_ids"][1]
    add_match(one, "a", won=True)
    add_match(two, "b", won=False)

    body = ladder_of(client, auth_headers, league["season_id"])

    team = next(t for t in body["teams"] if t["name"] == "Alpha")
    assert (team["ladder_points"], team["games"]) == (4, 2)
    # The loser leads the card: lose_first pays 25 where win_first pays 15
    assert (team["points"], team["games"]) == (4 + 15 + 25, 2)
    assert [player["id"] for player in team["players"]] == [two, one]


# The shapes the page draws.


def test_per_day_holds_one_row_a_day_and_the_last_mmr_of_it(
    client: Client, auth_headers: dict[str, str], league: dict[str, Any]
) -> None:
    player = league["player_ids"][0]
    add_match(player, "d1a", start_time=INSIDE, mmr_before=1500, mmr_after=1512)
    add_match(
        player,
        "d1b",
        start_time=INSIDE + timedelta(hours=2),
        won=False,
        mmr_before=1512,
        mmr_after=1499,
    )
    add_match(
        player,
        "d2",
        start_time=INSIDE + timedelta(days=1),
        mmr_before=1499,
        mmr_after=1520,
    )

    row = player_of(ladder_of(client, auth_headers, league["season_id"]), player)

    assert row["per_day"] == [
        {"d": "2026-01-07", "w": 1, "l": 1, "mmr": 1499},
        {"d": "2026-01-08", "w": 1, "l": 0, "mmr": 1520},
    ]
    assert row["mmr"] == {"start": 1500, "min": 1499, "max": 1520, "current": 1520}


def test_a_match_too_short_to_score_still_moves_the_mmr(
    client: Client, auth_headers: dict[str, str], league: dict[str, Any]
) -> None:
    """The duration rule pays points; it does not decide what the MMR did."""
    player = league["player_ids"][0]
    add_match(
        player,
        "drop-first",
        start_time=INSIDE,
        duration_s=60,
        won=False,
        mmr_before=1400,
        mmr_after=1380,
    )
    add_match(
        player,
        "game",
        start_time=INSIDE + timedelta(hours=1),
        mmr_before=1380,
        mmr_after=1392,
    )
    add_match(
        player,
        "drop-last",
        start_time=INSIDE + timedelta(hours=2),
        duration_s=60,
        won=False,
        mmr_before=1392,
        mmr_after=1370,
    )

    row = player_of(ladder_of(client, auth_headers, league["season_id"]), player)

    assert (row["games"], row["wins"], row["ladder_points"]) == (1, 1, 3)
    assert row["mmr"] == {"start": 1400, "min": 1370, "max": 1400, "current": 1370}


def test_a_placement_match_has_no_mmr_to_open_the_span_with(
    client: Client, auth_headers: dict[str, str], league: dict[str, Any]
) -> None:
    """w3champions publishes no MMR until the player is rated."""
    player = league["player_ids"][0]
    add_match(player, "place", start_time=INSIDE, mmr_before=None, mmr_after=None)
    add_match(
        player,
        "rated",
        start_time=INSIDE + timedelta(hours=1),
        mmr_before=1150,
        mmr_after=1160,
    )

    row = player_of(ladder_of(client, auth_headers, league["season_id"]), player)

    assert row["games"] == 2
    assert row["mmr"] == {"start": 1150, "min": 1150, "max": 1160, "current": 1160}


def test_vs_race_holds_every_race(
    client: Client, auth_headers: dict[str, str], league: dict[str, Any]
) -> None:
    player = league["player_ids"][0]
    add_match(player, "vs1", opp_race=Race.UD, won=True)
    add_match(
        player,
        "vs2",
        opp_race=Race.UD,
        won=False,
        start_time=INSIDE + timedelta(hours=1),
    )
    add_match(
        player,
        "vs3",
        opp_race=Race.OC,
        won=True,
        start_time=INSIDE + timedelta(hours=2),
    )

    row = player_of(ladder_of(client, auth_headers, league["season_id"]), player)

    assert row["vs_race"] == {
        "RANDOM": [0, 0],
        "HU": [0, 0],
        "OC": [1, 0],
        "NE": [0, 0],
        "UD": [1, 1],
    }


def test_by_hour_buckets_the_matches_by_utc_weekday_and_hour(
    client: Client, auth_headers: dict[str, str], league: dict[str, Any]
) -> None:
    """7 by 24, row 0 Sunday, and a match between two GNL players counts once."""
    one, two = league["player_ids"][0], league["player_ids"][2]
    # 2026-01-07 is a Wednesday, so row 3
    add_match(one, "shared", start_time=datetime(2026, 1, 7, 14, 30))
    add_match(two, "shared", start_time=datetime(2026, 1, 7, 14, 30), won=False)
    add_match(one, "sunday", start_time=datetime(2026, 1, 11, 0, 5))

    body = ladder_of(client, auth_headers, league["season_id"])

    assert len(body["by_hour"]) == 7
    assert {len(row) for row in body["by_hour"]} == {24}
    assert body["by_hour"][3][14] == 1
    assert body["by_hour"][0][0] == 1
    assert sum(sum(row) for row in body["by_hour"]) == 2


def test_the_season_carries_every_achievement_rule_once(
    client: Client, auth_headers: dict[str, str], league: dict[str, Any]
) -> None:
    """The catalogue is core.achievements, so no client copies the rules."""
    add_match(league["player_ids"][0], "one")

    body = ladder_of(client, auth_headers, league["season_id"])

    assert body["achievement_rules"] == [asdict(rule) for rule in ACHIEVEMENTS]


def test_the_season_stamp_is_the_oldest_of_the_roster(
    client: Client, auth_headers: dict[str, str], league: dict[str, Any]
) -> None:
    """Everyone is at least this fresh, which is what the page may claim."""
    add_match(league["player_ids"][0], "one")
    oldest = datetime(2026, 3, 1, 12, 30)
    for index, player in enumerate(league["player_ids"]):
        stamp_ladder(player, 25, oldest + timedelta(hours=index))

    body = ladder_of(client, auth_headers, league["season_id"])

    assert body["season"]["synced_at"] == oldest.isoformat()
    assert (
        player_of(body, league["player_ids"][1])["synced_at"]
        == (oldest + timedelta(hours=1)).isoformat()
    )


def test_a_season_with_a_player_never_read_is_unsynced(
    client: Client, auth_headers: dict[str, str], league: dict[str, Any]
) -> None:
    """One unread player is a season the page must not call synced."""
    add_match(league["player_ids"][0], "one")
    for player in league["player_ids"][:-1]:
        stamp_ladder(player, 25, datetime(2026, 3, 1, 12, 30))

    body = ladder_of(client, auth_headers, league["season_id"])

    assert body["season"]["synced_at"] is None
    assert player_of(body, league["player_ids"][-1])["synced_at"] is None


def test_a_player_short_of_one_season_of_the_window_is_unsynced(
    client: Client, auth_headers: dict[str, str], league: dict[str, Any]
) -> None:
    """The window sits in two w3champions seasons, so one stamp is not enough."""
    player = league["player_ids"][0]
    add_match(player, "one")
    add_match(player, "two", start_time=INSIDE + timedelta(days=1), wc3_season=24)
    stamp_ladder(player, 25, datetime(2026, 3, 1, 12, 30))

    body = ladder_of(client, auth_headers, league["season_id"])

    assert player_of(body, player)["synced_at"] is None
    stamp_ladder(player, 24, datetime(2026, 3, 1, 11, 0))
    body = ladder_of(client, auth_headers, league["season_id"])
    assert (
        player_of(body, player)["synced_at"] == datetime(2026, 3, 1, 11, 0).isoformat()
    )


def test_every_earned_achievement_is_in_the_catalogue(
    client: Client, auth_headers: dict[str, str], league: dict[str, Any]
) -> None:
    """A client draws the locked rules by subtracting the earned ids."""
    player = league["player_ids"][0]
    add_match(player, "won")

    body = ladder_of(client, auth_headers, league["season_id"])

    earned = {rule["id"] for rule in player_of(body, player)["achievements"]}
    assert earned == {"win_first"}
    assert earned <= {rule["id"] for rule in body["achievement_rules"]}


def test_the_season_per_day_counts_a_shared_match_once(
    client: Client, auth_headers: dict[str, str], league: dict[str, Any]
) -> None:
    """The series adds up to total_games, which the header shows."""
    one, two = league["player_ids"][0], league["player_ids"][2]
    add_match(one, "shared", won=True)
    add_match(two, "shared", won=False)
    add_match(one, "own", start_time=INSIDE + timedelta(days=2))

    body = ladder_of(client, auth_headers, league["season_id"])

    assert body["total_games"] == 2
    assert sum(day["g"] for day in body["per_day"]) == body["total_games"]
    played = {day["d"]: day["g"] for day in body["per_day"] if day["g"]}
    assert played == {"2026-01-07": 1, "2026-01-09": 1}


def test_the_season_per_day_covers_every_day_of_the_window(
    client: Client, auth_headers: dict[str, str], league: dict[str, Any]
) -> None:
    """A day nobody played reads 0, so the chart has no gap."""
    add_match(league["player_ids"][0], "one")

    body = ladder_of(client, auth_headers, league["season_id"])

    span = (date(2026, 2, 27) - date(2026, 1, 5)).days + 1
    assert len(body["per_day"]) == span
    assert body["per_day"][0] == {"d": "2026-01-05", "g": 0}
    assert body["per_day"][-1] == {"d": "2026-02-27", "g": 0}
    assert body["per_day"][2] == {"d": "2026-01-07", "g": 1}


def test_the_season_answer_costs_thirteen_statements(
    app: FastAPI, league: dict[str, Any]
) -> None:
    """The count is a constant: it does not grow with the number of players."""
    from app.services.ladder import LadderService

    for index, player in enumerate(league["player_ids"]):
        add_match(player, f"q{index}", start_time=INSIDE + timedelta(hours=index))

    with count_statements() as tally:
        body = LadderService().season_ladder(league["season_id"])

    assert body.total_games == 4
    # The rules are a constant and the day counts are the total_games group
    assert body.achievement_rules == ACHIEVEMENTS
    assert sum(day.g for day in body.per_day) == 4
    assert tally[0] == 13


# The achievement set: one instance per season, per rule.


def test_every_rule_a_new_season_pays_is_in_the_catalogue() -> None:
    """A row naming a rule the code does not know would never pay."""
    catalogue = {rule.id for rule in ACHIEVEMENTS}

    assert {row.rule_id for row in default_rows(None)} <= catalogue


def test_every_rule_the_migration_seeded_is_in_the_catalogue() -> None:
    """The seed is written out in the migration, so it can drift from the code."""
    path = next(
        (Path(__file__).parent.parent / "migrations" / "versions").glob(
            "a3d92f7c04be_*.py"
        )
    )
    spec = importlib.util.spec_from_file_location("ladder_achievements_seed", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    assert {rule_id for rule_id, _ in module.SEED} <= {rule.id for rule in ACHIEVEMENTS}


def rule_row_id(season_id: int, rule_id: str) -> int:
    with Session() as session:
        row = session.scalars(
            select(LadderAchievement).where(
                col(LadderAchievement.season_id) == season_id,
                col(LadderAchievement.rule_id) == rule_id,
            )
        ).one()
        assert row.id is not None
        return row.id


def repay(season_id: int, rule_id: str, **fields: int) -> None:
    """Change what one season pays for one rule, leaving other seasons alone."""
    row_id = rule_row_id(season_id, rule_id)
    with Session() as session:
        row = session.get(LadderAchievement, row_id)
        for key, value in fields.items():
            setattr(row, key, value)
        session.commit()


def test_a_season_pays_its_own_price_for_a_rule(
    client: Client, auth_headers: dict[str, str], league: dict[str, Any]
) -> None:
    """The same rule is two rows, so re-pricing one season moves only that one."""
    season = league["season_id"]
    other = second_season(season)
    player = league["player_ids"][0]
    sign_up(other, [player])
    add_match(player, "a", start_time=INSIDE)

    repay(season, "win_first", points=99)

    mine = player_of(ladder_of(client, auth_headers, season), player)
    resp = client.get(f"/users/{player}/ladder?season_id={other}", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    theirs = resp.json()

    assert [(b["id"], b["points"]) for b in mine["achievements"]] == [("win_first", 99)]
    assert [(b["id"], b["points"]) for b in theirs["achievements"]] == [
        ("win_first", 15)
    ]
    assert mine["points"] == mine["ladder_points"] + 99


def test_a_season_drops_a_rule_by_not_paying_it(
    client: Client, auth_headers: dict[str, str], league: dict[str, Any]
) -> None:
    season = league["season_id"]
    player = league["player_ids"][0]
    add_match(player, "a", start_time=INSIDE)

    row_id = rule_row_id(season, "win_first")
    with Session() as session:
        session.delete(session.get(LadderAchievement, row_id))
        session.commit()

    body = ladder_of(client, auth_headers, season)
    row = player_of(body, player)
    assert row["achievements"] == []
    assert row["points"] == row["ladder_points"]
    assert "win_first" not in {rule["id"] for rule in body["achievement_rules"]}


def test_a_rule_that_pays_per_match_pays_the_season_price(
    client: Client, auth_headers: dict[str, str], league: dict[str, Any]
) -> None:
    """The variable rules add their count to the season's price, not the code's."""
    season = league["season_id"]
    player = league["player_ids"][0]
    for index in range(11):
        add_match(player, f"r{index}", start_time=INSIDE + timedelta(hours=index))

    repay(season, "human", points=40)

    row = player_of(ladder_of(client, auth_headers, season), player)
    badge = next(b for b in row["achievements"] if b["id"] == "human")
    # 40 from the season, plus one for each of the eleven wins over Human
    assert badge["points"] == 51


# The player route.


def test_the_user_ladder_answers_the_window_of_the_season(
    client: Client, auth_headers: dict[str, str], league: dict[str, Any]
) -> None:
    player = league["player_ids"][0]
    add_match(player, "inside", start_time=INSIDE)
    add_match(player, "outside", start_time=datetime(2025, 12, 1, 12, 0))

    resp = client.get(
        f"/users/{player}/ladder?season_id={league['season_id']}", headers=auth_headers
    )

    assert resp.status_code == 200
    body = resp.json()
    assert body["games"] == 1
    assert [match["w3c_match_id"] for match in body["matches"]] == ["inside"]
    assert body["name"] == "P1"
    assert body["battleTag"] == "P1#1111"


def test_the_user_ladder_without_a_season_reads_every_match(
    client: Client, auth_headers: dict[str, str], league: dict[str, Any]
) -> None:
    """The all-time answer ignores the season window."""
    player = league["player_ids"][0]
    add_match(player, "inside", start_time=INSIDE)
    add_match(player, "outside", start_time=datetime(2025, 12, 1, 12, 0))

    body = client.get(f"/users/{player}/ladder", headers=auth_headers).json()

    assert body["games"] == 2
    assert [match["w3c_match_id"] for match in body["matches"]] == ["inside", "outside"]


def test_a_match_row_names_the_gnl_user_of_the_opponent(
    client: Client, auth_headers: dict[str, str], league: dict[str, Any]
) -> None:
    """The client opens that player from the row; an outsider reads null."""
    one, two = league["player_ids"][0], league["player_ids"][2]
    add_match(one, "gnl", opp_battletag="p3#3333", opp_race=Race.NE)
    add_match(
        one,
        "outsider",
        opp_battletag="Nobody#9999",
        start_time=INSIDE + timedelta(hours=1),
    )

    body = client.get(f"/users/{one}/ladder", headers=auth_headers).json()

    rows = {match["w3c_match_id"]: match for match in body["matches"]}
    assert rows["gnl"]["opp_user_id"] == two
    assert rows["outsider"]["opp_user_id"] is None
    assert rows["gnl"]["map_name"] == "Last Refuge"
    assert rows["gnl"]["race"] == "HU"
    assert rows["gnl"]["opp_race"] == "NE"
    assert rows["gnl"]["duration_s"] == 600
    assert (rows["gnl"]["mmr_before"], rows["gnl"]["mmr_after"]) == (1500, 1512)


def test_the_match_list_pages_like_every_other_list(
    client: Client, auth_headers: dict[str, str], league: dict[str, Any]
) -> None:
    """limit and offset, 1 to 500, and a page holds no row of another page."""
    player = league["player_ids"][0]
    for index in range(5):
        add_match(player, f"p{index}", start_time=INSIDE + timedelta(hours=index))

    url = f"/users/{player}/ladder"
    for query in ("limit=0", "limit=501", "offset=-1"):
        assert client.get(f"{url}?{query}", headers=auth_headers).status_code == 422

    first = client.get(f"{url}?limit=2", headers=auth_headers).json()
    second = client.get(f"{url}?limit=2&offset=2", headers=auth_headers).json()

    assert [match["w3c_match_id"] for match in first["matches"]] == ["p4", "p3"]
    assert [match["w3c_match_id"] for match in second["matches"]] == ["p2", "p1"]
    assert first["games"] == 5


# Auth and unknown ids.


def test_both_routes_need_a_token(client: Client, league: dict[str, Any]) -> None:
    assert client.get(f"/seasons/{league['season_id']}/ladder").status_code == 401
    assert client.get(f"/users/{league['player_ids'][0]}/ladder").status_code == 401


def test_both_routes_answer_404_for_an_unknown_id(
    client: Client, auth_headers: dict[str, str], league: dict[str, Any]
) -> None:
    season = client.get("/seasons/9999/ladder", headers=auth_headers)
    user = client.get("/users/9999/ladder", headers=auth_headers)
    window = client.get(
        f"/users/{league['player_ids'][0]}/ladder?season_id=9999", headers=auth_headers
    )

    assert season.status_code == 404
    assert season.json() == {"error": "Season not found"}
    assert user.status_code == 404
    assert user.json() == {"error": "User not found"}
    assert window.status_code == 404


def test_the_public_user_shape_carries_the_ladder_stamp(
    client: Client, auth_headers: dict[str, str], league: dict[str, Any]
) -> None:
    """Every public user answer says when his ladder matches were last read."""
    body = client.get(f"/users/{league['player_ids'][0]}").json()

    assert body["ladder_synced_at"] is None
    assert "w3c_synced_at" in body


def test_a_random_player_scores_his_random_picks_alone(
    client: Client, auth_headers: dict[str, str], league: dict[str, Any]
) -> None:
    """The rule reads the selected race, so RANDOM means the random picks."""
    player = league["player_ids"][0]
    with Session() as session:
        session.get(User, player).race = Race.RANDOM
        session.commit()
    add_match(player, "rolled", race=Race.RANDOM, played_race=Race.NE)
    add_match(player, "picked", race=Race.NE, start_time=INSIDE + timedelta(hours=1))

    body = ladder_of(client, auth_headers, league["season_id"])

    assert body["total_games"] == 1
    assert player_of(body, player)["games"] == 1


def test_a_random_pick_that_rolled_the_league_race_pays_nothing(
    client: Client, auth_headers: dict[str, str], league: dict[str, Any]
) -> None:
    """A player registered HU scores the HU he picked, not the HU he rolled."""
    player = league["player_ids"][0]
    add_match(player, "picked", race=Race.HU)
    add_match(
        player,
        "rolled",
        race=Race.RANDOM,
        played_race=Race.HU,
        start_time=INSIDE + timedelta(hours=1),
    )

    body = ladder_of(client, auth_headers, league["season_id"])

    assert body["total_games"] == 1
    assert player_of(body, player)["games"] == 1


def test_vs_race_buckets_a_random_opponent_under_random(
    client: Client, auth_headers: dict[str, str], league: dict[str, Any]
) -> None:
    """The versus panel reads the race the opponent selected, as wc3.no does."""
    player = league["player_ids"][0]
    add_match(player, "vs-random", opp_race=Race.RANDOM, opp_played_race=Race.UD)

    row = player_of(ladder_of(client, auth_headers, league["season_id"]), player)

    assert row["vs_race"]["RANDOM"] == [1, 0]
    assert row["vs_race"]["UD"] == [0, 0]


def test_the_signup_race_scores_the_season_it_belongs_to(
    client: Client, auth_headers: dict[str, str], league: dict[str, Any]
) -> None:
    """A season scores on the race its signup names, and users.race decides
    only where the signup names none. So re-registering on another race later
    leaves every past season where it stands."""
    player = league["player_ids"][0]  # registered HU on the user row
    add_match(player, "undead", race=Race.UD)
    add_match(player, "human", race=Race.HU, start_time=INSIDE + timedelta(hours=1))
    set_signup_race(league["season_id"], player, Race.UD)
    fallback = second_season(league["season_id"])
    sign_up(fallback, [player])

    on_signup = matches_of(client, auth_headers, player, league["season_id"])
    on_user = matches_of(client, auth_headers, player, fallback)

    assert on_signup == ["undead"]
    assert on_user == ["human"]
    assert ladder_of(client, auth_headers, league["season_id"])["total_games"] == 1
    assert ladder_of(client, auth_headers, fallback)["total_games"] == 1


def test_the_all_time_answer_reads_the_race_of_the_player(
    client: Client, auth_headers: dict[str, str], league: dict[str, Any]
) -> None:
    """It spans seasons, so it has no signup to read."""
    player = league["player_ids"][0]
    add_match(player, "undead", race=Race.UD)
    add_match(player, "human", race=Race.HU, start_time=INSIDE + timedelta(hours=1))
    set_signup_race(league["season_id"], player, Race.UD)

    body = client.get(f"/users/{player}/ladder", headers=auth_headers).json()

    assert [match["w3c_match_id"] for match in body["matches"]] == ["human"]


def test_a_match_on_another_race_is_practice(
    client: Client, auth_headers: dict[str, str], league: dict[str, Any]
) -> None:
    """The league locks a player to one race, so another race pays nothing."""
    player = league["player_ids"][0]
    add_match(player, "league", race=Race.HU)
    add_match(player, "practice", race=Race.UD, start_time=INSIDE + timedelta(hours=1))

    body = ladder_of(client, auth_headers, league["season_id"])

    assert body["total_games"] == 1
    assert player_of(body, player)["games"] == 1
