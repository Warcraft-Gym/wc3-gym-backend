"""The fantasy team writes a captain does itself.

The seeded fantasy team belongs to P1 (Discord id "1"). Its captain may
rename it and draft players; reseating the team stays with the admins.
"""

from typing import Any

import pytest
from httpx2 import Client

from tests.test_discord_auth import ACCOUNT, SESSION, stub_clerk


def test_the_captain_edits_and_drafts_its_own_team(
    client: Client, seeded: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    stub_clerk(monkeypatch, account={**ACCOUNT, "id": "1"})
    team_id = seeded["fantasy_team_id"]
    p2 = seeded["player_ids"][1]

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
    client: Client, seeded: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The leaderboard shows MMR and GNL record from the list answer alone."""
    stub_clerk(monkeypatch, account={**ACCOUNT, "id": "1"})
    resp = client.post(
        f"/fantasy/teams/{seeded['fantasy_team_id']}/players",
        json={"player_ids": [seeded["player_ids"][0]]},
        headers=SESSION,
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
    client: Client, seeded: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    stub_clerk(monkeypatch, account={**ACCOUNT, "id": "1"})
    team_id = seeded["fantasy_team_id"]
    p1, p2 = seeded["player_ids"][:2]

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
