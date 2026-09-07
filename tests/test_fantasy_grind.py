"""The grind pick: a bettor picks a second team, paid by its rank.

Teams of a season rank on the achievement points their players earned. With
N teams the rank r pays N - r + 1, a tie shares the rank, and a season that
offers no pick pays nothing.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx2 import Client

from app.core.db import Session
from app.core.fantasy import grind_points
from app.models.fantasy_team import FantasyTeam
from app.models.season import Season
from app.models.team import Team
from tests.test_fantasy_locks import schedule, score
from tests.test_ladder_read import add_match, sign_up
from tests.test_public_token import member_session


def test_the_rank_pays_and_a_tie_shares_it() -> None:
    """Three teams, two of them level, and one that played nothing."""
    points = {1: 40, 2: 40, 3: 0}
    assert grind_points(points, 1) == (1, 3)
    assert grind_points(points, 2) == (1, 3)
    assert grind_points(points, 3) == (3, 1)
    # A team outside the season pays nothing
    assert grind_points(points, 9) == (0, 0)


@pytest.fixture
def grind(seeded: dict[str, Any]) -> dict[str, Any]:
    """The seeded season offering the pick, with one badge on team Alpha.

    P1 plays team Alpha and wins a ladder game, so Alpha holds badge points
    and Beta holds none. Both fantasy teams pick their own GNL team.
    """
    sign_up(seeded["season_id"], seeded["player_ids"])
    add_match(seeded["player_ids"][0], "grind-1")
    with Session.begin() as session:
        session.get_one(Season, seeded["season_id"]).fantasy_grind = True
        session.get_one(FantasyTeam, seeded["fantasy_team_id"]).grind_team_id = seeded[
            "team_a_id"
        ]
        second = FantasyTeam(
            name="The Pessimists",
            season_id=seeded["season_id"],
            captain_id=seeded["player_ids"][1],
            drafted_team_id=seeded["team_b_id"],
            grind_team_id=seeded["team_b_id"],
        )
        session.add(second)
        session.flush()
        seeded["second_team_id"] = second.id
    return seeded


@pytest.fixture
def open_season(seeded: dict[str, Any]) -> dict[str, Any]:
    """The seeded season with nothing played, so a fantasy write is allowed."""
    score(seeded["series_played_id"], None, None)
    schedule(seeded["series_played_id"], datetime.now(UTC) + timedelta(days=1))
    return seeded


def team(client: Client, team_id: int) -> dict[str, Any]:
    resp = client.get(f"/fantasy/teams/{team_id}")
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_the_grind_pays_by_rank(client: Client, grind: dict[str, Any]) -> None:
    """Alpha earned the badge, so it ranks first of two and pays 2."""
    first = team(client, grind["fantasy_team_id"])
    second = team(client, grind["second_team_id"])
    assert (first["grind_points"], second["grind_points"]) == (2, 1)
    # The total counts the grind too
    assert first["total_points"] == sum(
        first[field]
        for field in (
            "player_points",
            "bench_points",
            "team_points",
            "race_points",
            "bet_points",
            "grind_points",
        )
    )


def test_a_season_without_the_pick_pays_nothing(
    client: Client, grind: dict[str, Any]
) -> None:
    with Session.begin() as session:
        session.get_one(Season, grind["season_id"]).fantasy_grind = False

    assert team(client, grind["fantasy_team_id"])["grind_points"] == 0
    resp = client.get(
        f"/fantasy/teams/{grind['fantasy_team_id']}"
        f"/season/{grind['season_id']}/breakdown"
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["grind_breakdown"] == {}
    assert resp.json()["totals"]["grind_points"] == 0


def test_the_breakdown_names_the_picked_team(
    client: Client, grind: dict[str, Any]
) -> None:
    resp = client.get(
        f"/fantasy/teams/{grind['fantasy_team_id']}"
        f"/season/{grind['season_id']}/breakdown"
    )
    assert resp.status_code == 200, resp.text
    breakdown = resp.json()["grind_breakdown"]
    assert breakdown["team_id"] == grind["team_a_id"]
    assert breakdown["team_name"] == "Alpha"
    assert breakdown["achievement_points"] > 0
    assert (breakdown["rank"], breakdown["teams"], breakdown["points"]) == (1, 2, 2)


def test_a_write_refuses_a_pick_the_season_does_not_offer(
    client: Client, open_season: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The season opens with no grind pick, so the write is refused."""
    headers = member_session(monkeypatch, "2", "p2")
    body = {
        "name": "Grinder",
        "season_id": open_season["season_id"],
        "drafted_team_id": open_season["team_a_id"],
        "drafted_race": "HU",
        "grind_team_id": open_season["team_a_id"],
    }
    resp = client.post("/fantasy-team", json=body, headers=headers)
    assert (resp.status_code, resp.json()) == (
        400,
        {"error": "This season offers no grind pick"},
    ), resp.text

    with Session.begin() as session:
        session.get_one(Season, open_season["season_id"]).fantasy_grind = True

    resp = client.post("/fantasy-team", json=body, headers=headers)
    assert resp.status_code == 201, resp.text
    assert resp.json()["grind_team_id"] == open_season["team_a_id"]
    team_id = resp.json()["id"]

    # The route answers 201 on the update path too, on the same team
    resp = client.post("/fantasy-team", json=body, headers=headers)
    assert (resp.status_code, resp.json()["id"]) == (201, team_id), resp.text


def test_a_write_refuses_a_team_outside_the_season(
    client: Client, open_season: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    headers = member_session(monkeypatch, "2", "p2")
    with Session.begin() as session:
        season = session.get_one(Season, open_season["season_id"])
        season.fantasy_grind = True
        outsider = Team(name="Outsider")
        session.add(outsider)
        session.flush()
        outsider_id = outsider.id

    resp = client.post(
        "/fantasy-team",
        json={
            "name": "Grinder",
            "season_id": open_season["season_id"],
            "drafted_team_id": open_season["team_a_id"],
            "drafted_race": "HU",
            "grind_team_id": outsider_id,
        },
        headers=headers,
    )
    assert (resp.status_code, resp.json()) == (
        400,
        {"error": "The grind team is not a team of this season"},
    ), resp.text
