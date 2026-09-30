"""Captains write and publish the weekly draft of matches their team plays.

Reads stay open to every captain. A captain of either team of the fixture
publishes (promote) its drafts, and an admin publishes any.
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
        f"/events/{seeded['season_id']}/teams/{seeded['team_a_id']}/captains",
        json={"captain_ids": [seeded["player_ids"][0]]},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text

    stub_clerk(monkeypatch, account={"id": "1", "username": "p1", "avatar": None})
    return SESSION


@pytest.fixture
def room(client: Client, seeded: dict[str, Any], auth_headers: dict[str, str]) -> None:
    """The seeded fixture already holds the two series of its round, and a
    fixture that is full refuses another pairing, so these tests widen it."""
    resp = client.put(
        f"/events/{seeded['season_id']}",
        json={"series_per_round": 6},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text


def draft_body(seeded: dict[str, Any]) -> dict[str, Any]:
    return {
        "match_id": seeded["match_id"],
        "player1_id": seeded["player_ids"][0],
        "player2_id": seeded["player_ids"][2],
        "host_player_id": seeded["player_ids"][0],
    }


def test_a_captain_drafts_his_own_match(
    client: Client, seeded: dict[str, Any], captain: dict[str, str], room: None
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


def captain_of_gamma(
    client: Client,
    seeded: dict[str, Any],
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, str]:
    """P2 captains Gamma, which does not play the seeded match, and his
    session sends these headers."""
    monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
    team = client.post(
        f"/leagues/{seeded['league_id']}/teams",
        json={"name": "Gamma"},
        headers=auth_headers,
    ).json()
    resp = client.post(
        f"/events/{seeded['season_id']}/teams",
        json={"team_ids": [team["id"]]},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    resp = client.put(
        f"/events/{seeded['season_id']}/teams/{team['id']}/captains",
        json={"captain_ids": [seeded["player_ids"][1]]},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    stub_clerk(monkeypatch, account={"id": "2", "username": "p2", "avatar": None})
    return SESSION


def test_a_captain_of_an_uninvolved_team_is_refused(
    client: Client,
    seeded: dict[str, Any],
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers = captain_of_gamma(client, seeded, auth_headers, monkeypatch)

    resp = client.post("/draft-series", json=draft_body(seeded), headers=headers)
    assert resp.status_code == 403, resp.text
    assert resp.json()["error"] == "Your team does not play this match"


def unplayed_pairing(seeded: dict[str, Any]) -> dict[str, Any]:
    """A pairing the seeded match holds no series for, so it can be published."""
    return {**draft_body(seeded), "player2_id": seeded["player_ids"][3]}


def test_a_captain_publishes_his_own_match(
    client: Client, seeded: dict[str, Any], captain: dict[str, str], room: None
) -> None:
    resp = client.post("/draft-series", json=unplayed_pairing(seeded), headers=captain)
    assert resp.status_code == 201, resp.text
    draft_id = resp.json()["id"]

    resp = client.post(f"/draft-series/{draft_id}/promote", headers=captain)
    assert resp.status_code == 201, resp.text
    assert resp.json()["player1_id"] == seeded["player_ids"][0]
    assert resp.json()["player2_id"] == seeded["player_ids"][3]

    resp = client.get(f"/draft-series/{draft_id}", headers=captain)
    assert resp.status_code == 404, resp.text


def test_a_captain_of_an_uninvolved_team_cannot_publish(
    client: Client,
    seeded: dict[str, Any],
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    room: None,
) -> None:
    resp = client.post(
        "/draft-series", json=unplayed_pairing(seeded), headers=auth_headers
    )
    assert resp.status_code == 201, resp.text
    draft_id = resp.json()["id"]
    headers = captain_of_gamma(client, seeded, auth_headers, monkeypatch)

    resp = client.post(f"/draft-series/{draft_id}/promote", headers=headers)
    assert resp.status_code == 403, resp.text
    assert resp.json()["error"] == "Your team does not play this match"


def test_a_member_cannot_publish(
    client: Client,
    seeded: dict[str, Any],
    captain: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    room: None,
) -> None:
    """P2 plays for Alpha but captains no team."""
    resp = client.post("/draft-series", json=draft_body(seeded), headers=captain)
    assert resp.status_code == 201, resp.text
    draft_id = resp.json()["id"]
    stub_clerk(monkeypatch, account={"id": "2", "username": "p2", "avatar": None})

    resp = client.post(f"/draft-series/{draft_id}/promote", headers=SESSION)
    assert resp.status_code == 403, resp.text


def test_a_captains_fantasy_mark_is_published(
    client: Client, seeded: dict[str, Any], captain: dict[str, str], room: None
) -> None:
    """The fantasy series is chosen on the draft and carried by the publish."""
    resp = client.post("/draft-series", json=unplayed_pairing(seeded), headers=captain)
    assert resp.status_code == 201, resp.text
    draft_id = resp.json()["id"]

    resp = client.put(
        f"/draft-series/{draft_id}",
        json={"is_fantasy_match": True},
        headers=captain,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["is_fantasy_match"] is True

    resp = client.post(f"/draft-series/{draft_id}/promote", headers=captain)
    assert resp.status_code == 201, resp.text
    assert resp.json()["is_fantasy_match"] is True


def test_a_promoted_draft_is_unplayed(
    client: Client,
    seeded: dict[str, Any],
    captain: dict[str, str],
    auth_headers: dict[str, str],
    room: None,
) -> None:
    """A draft carries no score, so the published series counts as unscored."""
    resp = client.post("/draft-series", json=unplayed_pairing(seeded), headers=captain)
    assert resp.status_code == 201, resp.text
    assert resp.json()["player1_score"] is None

    resp = client.post(
        f"/draft-series/{resp.json()['id']}/promote", headers=auth_headers
    )
    assert resp.status_code == 201, resp.text
    assert resp.json()["player1_score"] is None
    assert resp.json()["player2_score"] is None
