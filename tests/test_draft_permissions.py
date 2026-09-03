"""Captains write the weekly draft of matches their team plays.

Reads stay open to every captain, and publishing (promote) stays an admin act.
"""

from typing import Any

import pytest
from httpx2 import Client

from tests.test_discord_auth import SESSION, stub_clerk


@pytest.fixture
def captain(
    client: Client,
    seeded: dict[str, Any],
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, str]:
    """P1 captains Alpha this season, and his session sends these headers."""
    monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
    resp = client.put(
        f"/teams/{seeded['team_a_id']}/seasons/{seeded['season_id']}/captains",
        json={"captain_ids": [seeded["player_ids"][0]]},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text

    stub_clerk(monkeypatch, account={"id": "1", "username": "p1", "avatar": None})
    return SESSION


def draft_body(seeded: dict[str, Any]) -> dict[str, Any]:
    return {
        "match_id": seeded["match_id"],
        "player1_id": seeded["player_ids"][0],
        "player2_id": seeded["player_ids"][2],
        "host_player_id": seeded["player_ids"][0],
    }


def test_a_captain_drafts_his_own_match(
    client: Client, seeded: dict[str, Any], captain: dict[str, str]
) -> None:
    resp = client.post("/draft-series", json=draft_body(seeded), headers=captain)
    assert resp.status_code == 201, resp.text
    draft_id = resp.json()["id"]

    resp = client.put(
        f"/draft-series/{draft_id}",
        json={"player2_id": seeded["player_ids"][3]},
        headers=captain,
    )
    assert resp.status_code == 200, resp.text

    resp = client.delete(f"/draft-series/{draft_id}", headers=captain)
    assert resp.status_code == 204, resp.text


def test_a_captain_of_an_uninvolved_team_is_refused(
    client: Client,
    seeded: dict[str, Any],
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """P2 captains Gamma, which does not play the seeded match."""
    monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
    team = client.post("/teams", json={"name": "Gamma"}, headers=auth_headers).json()
    resp = client.post(
        f"/seasons/{seeded['season_id']}/teams",
        json={"team_ids": [team["id"]]},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    resp = client.put(
        f"/teams/{team['id']}/seasons/{seeded['season_id']}/captains",
        json={"captain_ids": [seeded["player_ids"][1]]},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    stub_clerk(monkeypatch, account={"id": "2", "username": "p2", "avatar": None})

    resp = client.post("/draft-series", json=draft_body(seeded), headers=SESSION)
    assert resp.status_code == 403, resp.text
    assert resp.json()["error"] == "Your team does not play this match"


def test_promote_stays_an_admin_act(
    client: Client, seeded: dict[str, Any], captain: dict[str, str]
) -> None:
    resp = client.post("/draft-series", json=draft_body(seeded), headers=captain)
    assert resp.status_code == 201, resp.text
    draft_id = resp.json()["id"]

    resp = client.post(f"/draft-series/{draft_id}/promote", headers=captain)
    assert resp.status_code == 403, resp.text


def test_a_promoted_draft_is_unplayed(
    client: Client,
    seeded: dict[str, Any],
    captain: dict[str, str],
    auth_headers: dict[str, str],
) -> None:
    """A draft carries no score, so the published series counts as unscored."""
    body = {**draft_body(seeded), "player2_id": seeded["player_ids"][3]}
    resp = client.post("/draft-series", json=body, headers=captain)
    assert resp.status_code == 201, resp.text
    assert resp.json()["player1_score"] is None

    resp = client.post(
        f"/draft-series/{resp.json()['id']}/promote", headers=auth_headers
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["player1_score"] is None
    assert resp.json()["player2_score"] is None
