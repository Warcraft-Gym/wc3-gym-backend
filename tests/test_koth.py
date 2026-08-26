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


@pytest.fixture
def w3c_mmr(monkeypatch: pytest.MonkeyPatch) -> None:
    """The signup path with the two w3champions calls answered from memory."""
    from app.models.enums import Race
    from app.models.w3c_stats import W3CStatsCreate
    from app.services.w3c import W3CService

    monkeypatch.setattr(W3CService, "current_season", lambda self: 20)
    monkeypatch.setattr(
        W3CService,
        "get_player_stats",
        lambda self, bnet_name, season_override=None: [
            W3CStatsCreate(wc3_season=season_override, mmr=1400, race=Race.HU)
        ],
    )
    monkeypatch.setattr(
        W3CService,
        "send_request",
        lambda *args, **kwargs: pytest.fail("the signup reached w3champions"),
    )


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


def test_a_second_signup_of_the_same_race_adds_no_row(
    app: FastAPI, koth: dict[str, Any], w3c_mmr: None
) -> None:
    """The second of two signups that arrive together answers the duplicate."""
    from app.services.koth import KothService

    service = KothService()
    first = service.create_signup_from_twitch("player_three", "P3#3333", "human")
    assert first.race == "HU"

    with pytest.raises(Exception, match="already has an active signup"):
        service.create_signup_from_twitch("player_three", "P3#3333", "human")

    signups = service.get_signups_by_event(koth["event_id"])
    assert [s.twitch_username for s in signups].count("player_three") == 1


def test_the_database_holds_one_active_signup_per_name_and_race(
    app: FastAPI, koth: dict[str, Any]
) -> None:
    """The unique index, not the service, is what two requests at once meet."""
    from sqlalchemy.exc import IntegrityError

    from app.core.db import Session
    from app.models.enums import Race
    from app.models.koth_signup import KothSignup

    def signup(race: Race) -> KothSignup:
        return KothSignup(
            event_id=koth["event_id"],
            twitch_username="player_one",
            battle_tag="P1#1111",
            w3c_name="P1",
            mmr=1400,
            bracket=1,
            race=race,
        )

    with Session() as session, pytest.raises(IntegrityError):
        session.add(signup(Race.HU))
        session.commit()

    # Another race, and the same race once the first signup retires, both fit
    with Session() as session:
        session.add(signup(Race.NE))
        session.commit()
        session.query(KothSignup).filter_by(race=Race.HU).update({"is_active": 0})
        session.add(signup(Race.HU))
        session.commit()

    with Session() as session:
        assert session.query(KothSignup).count() == 4


def test_one_event_is_active_after_an_activation(
    client: Client, auth_headers: dict[str, str], koth: dict[str, Any]
) -> None:
    second = client.post(
        "/koth/events", headers=auth_headers, json={"name": "KOTH 2"}
    ).json()

    def active_ids() -> list[int]:
        return [e["id"] for e in client.get("/koth/events").json() if e["is_active"]]

    for event_id in (koth["event_id"], second["id"]):
        resp = client.post(f"/koth/events/{event_id}/activate", headers=auth_headers)
        assert resp.status_code == 200, resp.text
        assert resp.json()["is_active"] is True
        assert active_ids() == [event_id]

    assert (
        client.post("/koth/events/9999/activate", headers=auth_headers).status_code
        == 404
    )
    assert active_ids() == [second["id"]]


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


def test_an_admin_signup_needs_no_w3c_configuration(
    client: Client,
    auth_headers: dict[str, str],
    koth: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Nothing names the season or the API, so the signup takes the default
    base URL and the season w3champions reports."""
    from app.models.enums import Race
    from app.models.w3c_stats import W3CStatsCreate
    from app.services.w3c import DEFAULT_BASE_URL, W3CService

    monkeypatch.delenv("W3C_URL", raising=False)
    asked: dict[str, Any] = {}

    def fake_send_request(
        self: W3CService, method: str, url: str, **kwargs: object
    ) -> list[dict[str, int]]:
        asked["seasons_url"] = url
        return [{"id": 25}, {"id": 24}]

    def fake_stats(
        self: W3CService, bnet_name: str, season_override: int | None = None
    ) -> list[W3CStatsCreate]:
        asked["stats_base"] = self.base_url()
        asked["season"] = season_override
        return [W3CStatsCreate(wc3_season=season_override, mmr=1400, race=Race.HU)]

    monkeypatch.setattr(W3CService, "send_request", fake_send_request)
    monkeypatch.setattr(W3CService, "get_player_stats", fake_stats)

    resp = client.post(
        "/koth/signups/admin",
        headers=auth_headers,
        json={"twitch_username": "player_three", "battle_tag": "P3#3333"},
    )

    assert resp.status_code == 201, resp.text
    assert asked["seasons_url"] == f"{DEFAULT_BASE_URL}/ladder/seasons"
    assert asked["stats_base"] == DEFAULT_BASE_URL
    assert asked["season"] == 25
