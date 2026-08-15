"""The King of the Hill flows that write rows.

The signup endpoint reaches w3champions, so these tests insert the
signups through the session and then drive the match, king and bracket
endpoints through the API.
"""

from typing import Any

import pytest
from fastapi import FastAPI
from httpx2 import Client


@pytest.fixture
def koth(app: FastAPI, seeded: dict[str, Any]) -> dict[str, Any]:
    """An active event with two signups in bracket 1."""
    from app.core.db import Session
    from app.models.enums import Race
    from app.models.koth_event import KothEvent
    from app.models.koth_signup import KothSignup

    with Session() as session:
        event = session.query(KothEvent).filter_by(name="KOTH 1").one()
        one = KothSignup(
            event_id=event.id,
            twitch_username="player_one",
            battle_tag="P1#1111",
            w3c_name="P1",
            race=Race.HU,
            mmr=1400,
            bracket=1,
        )
        two = KothSignup(
            event_id=event.id,
            twitch_username="player_two",
            battle_tag="P2#2222",
            w3c_name="P2",
            race=Race.OC,
            mmr=1420,
            bracket=1,
        )
        session.add_all([one, two])
        session.commit()
        return {"event_id": event.id, "signup_ids": [one.id, two.id]}


def test_the_event_carries_its_signups(client: Client, koth: dict[str, Any]) -> None:
    event = client.get(f"/koth/events/{koth['event_id']}").json()
    assert len(event["signups"]) == 2
    # The race reads as the plain value, not the name of the enum member.
    assert sorted(s["race"] for s in event["signups"]) == ["HU", "OC"]
    assert all(s["is_active"] == 1 and s["is_king"] == 0 for s in event["signups"])


def test_a_match_takes_its_bracket_from_the_participants(
    client: Client, auth_headers: dict[str, str], koth: dict[str, Any]
) -> None:
    one, two = koth["signup_ids"]
    resp = client.post(
        "/koth/matches",
        headers=auth_headers,
        json={
            "event_id": koth["event_id"],
            "game_mode": "1v1",
            "num_teams": 2,
            "participants": [
                {"signup_id": one, "team_number": 1},
                {"signup_id": two, "team_number": 2},
            ],
        },
    )
    assert resp.status_code == 201, resp.text
    match = resp.json()
    assert match["bracket"] == 1
    assert len(match["participants"]) == 2
    assert {p["signup"]["battle_tag"] for p in match["participants"]} == {
        "P1#1111",
        "P2#2222",
    }


def test_a_result_crowns_the_winner_and_retires_the_loser(
    client: Client, auth_headers: dict[str, str], koth: dict[str, Any]
) -> None:
    one, two = koth["signup_ids"]
    match = client.post(
        "/koth/matches",
        headers=auth_headers,
        json={
            "event_id": koth["event_id"],
            "game_mode": "1v1",
            "num_teams": 2,
            "participants": [
                {"signup_id": one, "team_number": 1},
                {"signup_id": two, "team_number": 2},
            ],
        },
    ).json()

    resp = client.put(
        f"/koth/matches/{match['id']}/result",
        headers=auth_headers,
        json={"winner_team_number": 1},
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["winner_team_number"] == 1

    signups = {
        s["id"]: s
        for s in client.get(f"/koth/events/{koth['event_id']}").json()["signups"]
    }
    assert signups[one]["is_king"] == 1
    assert signups[one]["is_active"] == 1
    assert signups[two]["is_king"] == 0
    assert signups[two]["is_active"] == 0


def test_a_bracket_change_touches_only_the_bracket(
    client: Client, auth_headers: dict[str, str], koth: dict[str, Any]
) -> None:
    one = koth["signup_ids"][0]
    before = client.get(f"/koth/events/{koth['event_id']}").json()["signups"]
    before = next(s for s in before if s["id"] == one)

    resp = client.put(
        f"/koth/signups/{one}/bracket", headers=auth_headers, json={"bracket": 3}
    )
    assert resp.status_code == 200, resp.text
    after = resp.json()
    assert after["bracket"] == 3
    for field in ("battle_tag", "w3c_name", "race", "mmr", "is_king", "is_active"):
        assert after[field] == before[field]


def test_the_king_endpoints_move_the_crown(
    client: Client, auth_headers: dict[str, str], koth: dict[str, Any]
) -> None:
    one, two = koth["signup_ids"]

    assert (
        client.post(f"/koth/signups/{one}/king", headers=auth_headers).status_code
        == 200
    )
    kings = client.get(f"/koth/events/{koth['event_id']}/kings").json()
    assert [s["id"] for s in kings["1"]] == [one]

    # set_king clears the other king in the bracket, add-king does not.
    assert (
        client.post(f"/koth/signups/{two}/king", headers=auth_headers).status_code
        == 200
    )
    kings = client.get(f"/koth/events/{koth['event_id']}/kings").json()
    assert [s["id"] for s in kings["1"]] == [two]

    assert (
        client.post(f"/koth/signups/{one}/add-king", headers=auth_headers).status_code
        == 200
    )
    kings = client.get(f"/koth/events/{koth['event_id']}/kings").json()
    assert sorted(s["id"] for s in kings["1"]) == sorted([one, two])

    assert (
        client.delete(f"/koth/signups/{two}/king", headers=auth_headers).status_code
        == 200
    )
    kings = client.get(f"/koth/events/{koth['event_id']}/kings").json()
    assert [s["id"] for s in kings["1"]] == [one]


def test_an_event_update_keeps_the_fields_it_was_not_given(
    client: Client, auth_headers: dict[str, str], koth: dict[str, Any]
) -> None:
    before = client.get(f"/koth/events/{koth['event_id']}").json()
    resp = client.put(
        f"/koth/events/{koth['event_id']}",
        headers=auth_headers,
        json={"description": "now with a description"},
    )
    assert resp.status_code == 200, resp.text
    after = resp.json()
    assert after["description"] == "now with a description"
    assert after["name"] == before["name"]
    assert after["event_date"] == before["event_date"]
    assert after["bracket_1_threshold"] == before["bracket_1_threshold"]


def test_bad_koth_input_answers_400(
    client: Client, auth_headers: dict[str, str], koth: dict[str, Any]
) -> None:
    """The rule checks in the service answer 400, not 500."""
    one, two = koth["signup_ids"]

    resp = client.put(
        f"/koth/signups/{one}/bracket", headers=auth_headers, json={"bracket": 9}
    )
    assert resp.status_code == 400
    assert "Bracket" in resp.json()["error"]

    resp = client.post(
        "/koth/matches",
        headers=auth_headers,
        json={
            "event_id": koth["event_id"],
            "game_mode": "1v1",
            "num_teams": 2,
            "participants": [
                {"signup_id": one, "team_number": 1},
                {"signup_id": two, "team_number": 1},
            ],
        },
    )
    assert resp.status_code == 400
    assert "teams" in resp.json()["error"]

    match = client.post(
        "/koth/matches",
        headers=auth_headers,
        json={
            "event_id": koth["event_id"],
            "game_mode": "1v1",
            "num_teams": 2,
            "participants": [
                {"signup_id": one, "team_number": 1},
                {"signup_id": two, "team_number": 2},
            ],
        },
    ).json()
    resp = client.put(
        f"/koth/matches/{match['id']}/result",
        headers=auth_headers,
        json={"winner_team_number": 5},
    )
    assert resp.status_code == 400
    assert "Winner team number" in resp.json()["error"]
