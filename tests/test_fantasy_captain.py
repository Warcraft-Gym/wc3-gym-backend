"""The fantasy team writes a captain does itself.

The seeded fantasy team belongs to P1 (Discord id "1"). Its captain may
rename it and draft players while the season is open; reseating the team
stays with the admins, and a commenced season closes every owner write.
"""

from datetime import timedelta
from typing import Any

import pytest
from httpx2 import Client

from app.models.enums import Race
from app.models.types import utcnow
from tests.test_discord_auth import ACCOUNT, SESSION, stub_clerk
from tests.test_fantasy_locks import COMMENCED, schedule, score


@pytest.fixture
def open_season(
    client: Client, seeded: dict[str, Any], auth_headers: dict[str, str]
) -> dict[str, Any]:
    """The seed's one played series decides the phase; unplayed and set later,
    the season is open. Its four players sign up and take a tier from their MMR:
    P1 tier 1, P2 and P4 tier 2, P3 tier 3."""
    from tests.test_ladder_read import add_match, sign_up

    score(seeded["series_played_id"], None, None)
    schedule(seeded["series_played_id"], utcnow() + timedelta(days=1))
    p1, p2, p3, p4 = seeded["player_ids"][:4]
    sign_up(seeded["season_id"], [p1, p2, p3, p4], race=Race.HU)
    when = utcnow() + timedelta(minutes=5)
    for user_id, mmr in ((p1, 1400), (p2, 1200), (p3, 1000), (p4, 1250)):
        add_match(
            user_id,
            f"m{user_id}",
            when,
            mmr_before=mmr,
            mmr_after=mmr,
            race=Race.HU,
        )
    resp = client.put(
        f"/fantasy/tiers?season_id={seeded['season_id']}",
        json={"cuts": [1100, 1300], "tiers": {}},
        headers=auth_headers,
    )
    assert resp.status_code == 204, resp.text
    return seeded


def test_the_captain_edits_and_drafts_its_own_team(
    client: Client, open_season: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    stub_clerk(monkeypatch, account={**ACCOUNT, "id": "1"})
    team_id = open_season["fantasy_team_id"]
    p2 = open_season["player_ids"][1]

    resp = client.put(
        f"/fantasy/teams/{team_id}", json={"name": "Renamed"}, headers=SESSION
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["name"] == "Renamed"

    resp = client.post(
        f"/fantasy/teams/{team_id}/players",
        json={"player_ids": [p2]},
        headers=SESSION,
    )
    assert resp.status_code == 200, resp.text
    assert [p["id"] for p in resp.json()["drafted_players"]] == [p2]

    resp = client.request(
        "DELETE",
        f"/fantasy/teams/{team_id}/players",
        json={"player_ids": [p2]},
        headers=SESSION,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["drafted_players"] == []


def test_the_list_answers_the_drafted_players_stats(
    client: Client, seeded: dict[str, Any], auth_headers: dict[str, str]
) -> None:
    """The leaderboard shows MMR and GNL record from the list answer alone."""
    resp = client.post(
        f"/fantasy/teams/{seeded['fantasy_team_id']}/players",
        json={"player_ids": [seeded["player_ids"][0]]},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text

    resp = client.post("/fantasy/teams/search?query=season_id > 0")
    assert resp.status_code == 200
    player = resp.json()[0]["drafted_players"][0]
    assert player["w3c_stats"] == []
    # P1 won the one played series, and the derived fill counts it
    gnl = player["gnl_stats"][0]
    assert (gnl["wins"], gnl["losses"], gnl["games"]) == (1, 0, 1)


def test_a_member_who_is_not_the_captain_is_refused(
    client: Client, seeded: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    stub_clerk(monkeypatch, account={**ACCOUNT, "id": "2"})
    resp = client.put(
        f"/fantasy/teams/{seeded['fantasy_team_id']}",
        json={"name": "Taken over"},
        headers=SESSION,
    )
    assert resp.status_code == 403
    assert resp.json() == {"error": "Admins or the fantasy team's owner only"}


def test_the_captain_cannot_reseat_the_team(
    client: Client, open_season: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    stub_clerk(monkeypatch, account={**ACCOUNT, "id": "1"})
    team_id = open_season["fantasy_team_id"]
    p1, p2 = open_season["player_ids"][:2]

    resp = client.put(
        f"/fantasy/teams/{team_id}", json={"captain_id": p2}, headers=SESSION
    )
    assert resp.status_code == 403
    assert resp.json() == {"error": "Only admins reassign the owner or season"}

    # The unchanged seat passes, so the frontend may echo the whole form
    resp = client.put(
        f"/fantasy/teams/{team_id}",
        json={"name": "Still mine", "captain_id": p1},
        headers=SESSION,
    )
    assert resp.status_code == 200, resp.text


def test_a_commenced_season_closes_the_captain_writes(
    client: Client,
    seeded: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    auth_headers: dict[str, str],
) -> None:
    """The seeded season has a played series, so the draft it scores is settled.

    The admin routes stay open, so a mistake is still fixed there.
    """
    stub_clerk(monkeypatch, account={**ACCOUNT, "id": "1"})
    team_id = seeded["fantasy_team_id"]
    p2 = seeded["player_ids"][1]

    resp = client.put(
        f"/fantasy/teams/{team_id}",
        json={"drafted_team_id": seeded["team_b_id"]},
        headers=SESSION,
    )
    assert (resp.status_code, resp.json()) == (403, COMMENCED), resp.text

    resp = client.post(
        f"/fantasy/teams/{team_id}/players",
        json={"player_ids": [p2]},
        headers=SESSION,
    )
    assert (resp.status_code, resp.json()) == (403, COMMENCED), resp.text

    resp = client.request(
        "DELETE",
        f"/fantasy/teams/{team_id}/players",
        json={"player_ids": [p2]},
        headers=SESSION,
    )
    assert (resp.status_code, resp.json()) == (403, COMMENCED), resp.text

    resp = client.put(
        f"/fantasy/teams/{team_id}",
        json={"drafted_team_id": seeded["team_b_id"]},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text


def test_an_owner_keeps_one_player_per_tier(
    client: Client,
    open_season: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    auth_headers: dict[str, str],
) -> None:
    """The owner routes apply the draft rule the public draft applies: one
    player per tier, and no more than the season's tiers. An admin reseats freely."""
    stub_clerk(monkeypatch, account={**ACCOUNT, "id": "1"})
    team_id = open_season["fantasy_team_id"]
    p1, p2, p3, p4 = open_season["player_ids"][:4]
    refused = {"error": "A fantasy team drafts one player from each of the 3 tiers"}

    resp = client.post(
        f"/fantasy/teams/{team_id}/players",
        json={"player_ids": [p1, p2, p3]},
        headers=SESSION,
    )
    assert resp.status_code == 200, resp.text

    # P4 shares P2's tier, and he would be a fourth player besides
    resp = client.post(
        f"/fantasy/teams/{team_id}/players",
        json={"player_ids": [p4]},
        headers=SESSION,
    )
    assert (resp.status_code, resp.json()) == (400, refused), resp.text
    team = client.get(f"/fantasy/teams/{team_id}").json()
    assert {player["id"] for player in team["drafted_players"]} == {p1, p2, p3}

    resp = client.post(
        f"/fantasy/teams/{team_id}/players",
        json={"player_ids": [p4]},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
