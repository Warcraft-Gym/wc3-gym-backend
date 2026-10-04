"""The list rows of an event's teams against the roster read.

GET /events/{event_id}/teams answers TeamRosterPublic, the detail; the summary
answers the same teams as list rows. The detail is the oracle: every field the
summary carries equals the detail field it comes from. A player's MMR is the
MMR he entered a finished event with, else the rating of his signup race in
the ladder summary.
"""

from datetime import timedelta
from typing import Any

import pytest
from httpx2 import Client

from app.core.db import Session
from app.models.enums import Race
from app.models.match import Match
from app.models.relationships import DBTeamSeasonCaptain, DBUserSeasonSignup
from app.models.season import Season
from app.models.series import Series
from app.models.types import utcnow
from app.models.user_battle_tag import UserBattleTag
from tests.test_series_row_mmr import (  # noqa: F401  # finished is a fixture
    finished,
    play,
    rate,
)

PERSON = ("id", "name", "battleTag", "country", "signup_race", "played_as")


@pytest.fixture
def rosters(finished: dict[str, Any]) -> dict[str, Any]:  # noqa: F811
    """The finished seeded season with captains on both teams, a signup tag, an
    old tag, a second match that team B holds as team1 and the ladder rows of
    the MMR the players entered with."""
    p1, p2, p3, p4 = finished["player_ids"]
    season_id = finished["season_id"]
    with Session.begin() as session:
        session.add_all(
            DBTeamSeasonCaptain(team_id=team_id, season_id=season_id, user_id=user_id)
            for team_id, user_id in (
                (finished["team_a_id"], p2),
                (finished["team_a_id"], p1),
                (finished["team_b_id"], p4),
            )
        )
        signup = session.get_one(DBUserSeasonSignup, (p1, season_id))
        signup.played_as = "Pone#1"
        session.add(
            UserBattleTag(user_id=p1, tag="Old#9999", source="sheet", is_active=False)
        )
        second = Match(
            team1_id=finished["team_b_id"],
            team2_id=finished["team_a_id"],
            season_id=season_id,
            playday=2,
        )
        session.add(second)
        session.flush()
        session.add(
            Series(
                match_id=second.id,
                player1_id=p4,
                player2_id=p2,
                player1_score=2,
                player2_score=0,
                host_player_id=p4,
            )
        )
    play(p1, Race.HU, -70, 25, (1400, 1410))
    play(p1, Race.HU, -60, 25, (1420, 1440))
    play(p3, Race.NE, -72, 25, (1500, 1505))
    return finished


def summary_of(team: dict[str, Any], event_id: int, running: bool) -> dict[str, Any]:
    """The summary fields of one detail team, as the detail answers them."""
    key = str(event_id)
    info = next(i for i in team["seasons_info"] if i["season_id"] == event_id)

    def mmr(player: dict[str, Any]) -> int | None:
        if not running:
            return player["mmr_entered"]
        return next(
            (
                race["mmr"]
                for race in player["race_mmrs"]
                if race["race"] == player["signup_race"] and race["mmr"] is not None
            ),
            None,
        )

    def person(player: dict[str, Any]) -> dict[str, Any]:
        return {field: player[field] for field in PERSON}

    players = sorted(team["player_by_season"][key], key=lambda player: player["id"])
    return {
        "id": team["id"],
        "league_id": team["league_id"],
        "name": team["name"],
        "long_name": team["long_name"],
        "icon_url": team["icon_url"],
        "final_score": info["final_score"],
        "players": [
            person(player)
            | {
                "tags": [tag["tag"] for tag in player["tags"]],
                "wins": player["record"]["wins"],
                "losses": player["record"]["losses"],
                "mmr": mmr(player),
            }
            for player in players
        ],
        "captains": [person(c) for c in team["captains_by_season"][key]],
    }


def compare(client: Client, event_id: int, running: bool) -> list[dict[str, Any]]:
    """Both reads of the event, the summary held equal to the detail."""
    detail = client.get(f"/events/{event_id}/teams")
    summary = client.get(f"/events/{event_id}/teams/summary")
    assert detail.status_code == summary.status_code == 200
    assert summary.headers["Cache-Control"] == detail.headers["Cache-Control"]
    expected = [summary_of(team, event_id, running) for team in detail.json()]
    assert summary.json() == expected
    return summary.json()


def test_the_summary_equals_the_roster_read_on_a_finished_event(
    client: Client, rosters: dict[str, Any]
) -> None:
    p1, p2, p3, p4 = rosters["player_ids"]
    team_a, team_b = compare(client, rosters["season_id"], running=False)
    players = {p["id"]: p for p in team_a["players"] + team_b["players"]}
    # The compared rows hold a record, a tag list, a signup tag and an MMR
    assert players[p1]["tags"] == ["P1#1111", "Old#9999"]
    assert players[p1]["played_as"] == "Pone#1"
    assert players[p1]["signup_race"] == "HU"
    assert (players[p1]["wins"], players[p2]["losses"], players[p4]["wins"]) == (
        1,
        1,
        1,
    )
    assert [players[p]["mmr"] for p in (p1, p2, p3, p4)] == [1420, None, 1505, None]
    assert [c["id"] for c in team_a["captains"]] == sorted([p1, p2])
    assert [c["id"] for c in team_b["captains"]] == [p4]
    assert team_a["final_score"] and team_b["final_score"]


def test_the_summary_equals_the_roster_read_on_a_running_event(
    client: Client, rosters: dict[str, Any]
) -> None:
    """P1's newest window row on his race has no rating, so the one before it
    counts; P2 is rated on another race only, P4 not at all."""
    p1, p2, p3, p4 = rosters["player_ids"]
    with Session.begin() as session:
        season = session.get_one(Season, rosters["season_id"])
        season.end_date = utcnow().date() + timedelta(days=30)
    rate(
        (p1, Race.HU, 24, 1600),
        (p1, Race.HU, 25, None),
        (p1, Race.OC, 25, 1700),
        (p2, Race.UD, 25, 1650),
        (p3, Race.NE, 25, 1550),
        (p3, Race.NE, 23, 1900),
    )
    teams = compare(client, rosters["season_id"], running=True)
    mmr = {p["id"]: p["mmr"] for team in teams for p in team["players"]}
    assert mmr == {p1: 1600, p2: None, p3: 1550, p4: None}


def test_the_page_and_the_order_are_those_of_the_roster_read(
    client: Client, rosters: dict[str, Any]
) -> None:
    base = f"/events/{rosters['season_id']}/teams"
    for query in ("", "?limit=1", "?limit=1&offset=1", "?offset=2"):
        detail = [team["id"] for team in client.get(f"{base}{query}").json()]
        found = [team["id"] for team in client.get(f"{base}/summary{query}").json()]
        assert found == detail
    assert client.get(f"{base}/summary?limit=501").status_code == 422


def test_a_missing_event_answers_an_empty_list(client: Client) -> None:
    response = client.get("/events/987654/teams/summary")
    assert response.status_code == 200
    assert response.json() == []
