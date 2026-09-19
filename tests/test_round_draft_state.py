"""What the captains keep beside the pairings of one fixture.

Who wrote and who changed a pairing, the Ready and seen marks per team, the
working largest MMR difference, the round count, and the draft that replaces a
published series.
"""

from collections.abc import Callable
from typing import Any

import pytest
from httpx2 import Client


@pytest.fixture
def draft(
    client: Client,
    seeded: dict[str, Any],
    auth_headers: dict[str, str],
    member: Callable[..., dict[str, str]],
) -> dict[str, Any]:
    """Both captains seated, a captain-draft stage, and the ids the tests use.

    P1 captains Alpha, P3 captains Beta and P4 is a plain roster member.
    """
    for team, place in ((seeded["team_a_id"], 0), (seeded["team_b_id"], 2)):
        seated = client.put(
            f"/teams/{team}/seasons/{seeded['season_id']}/captains",
            json={"captain_ids": [seeded["player_ids"][place]]},
            headers=auth_headers,
        )
        assert seated.status_code == 200, seated.text
    staged = client.put(
        f"/events/{seeded['season_id']}/stages",
        json=[{"name": "Draft", "format": "gnl"}],
        headers=auth_headers,
    )
    assert staged.status_code == 200, staged.text
    return {
        "match_id": seeded["match_id"],
        "team_a": seeded["team_a_id"],
        "team_b": seeded["team_b_id"],
        "players": seeded["player_ids"],
        "season_id": seeded["season_id"],
        "captain_a": member("1"),
        "captain_b": member("3"),
        "plain": member("4"),
    }


def widen(client: Client, headers: dict[str, str], season_id: int) -> None:
    """The seeded fixture holds both series of its round, so make room."""
    resp = client.put(
        f"/events/{season_id}", json={"series_per_round": 6}, headers=headers
    )
    assert resp.status_code == 200, resp.text


def pairing(draft: dict[str, Any], one: int = 0, two: int = 3) -> dict[str, Any]:
    return {
        "match_id": draft["match_id"],
        "player1_id": draft["players"][one],
        "player2_id": draft["players"][two],
        "host_player_id": draft["players"][one],
    }


def test_a_pairing_names_who_wrote_it_and_who_changed_it(
    client: Client, draft: dict[str, Any], auth_headers: dict[str, str]
) -> None:
    widen(client, auth_headers, draft["season_id"])
    made = client.post("/draft-series", json=pairing(draft), headers=draft["captain_a"])

    assert made.status_code == 201, made.text
    body = made.json()
    assert body["created_by_user_id"] == draft["players"][0]
    assert body["created_by_name"] == "P1"
    assert body["updated_by_name"] == "P1"
    assert body["updated_at"] is not None

    changed = client.put(
        f"/draft-series/{body['id']}",
        json={"player2_id": draft["players"][2]},
        headers=draft["captain_b"],
    )
    assert changed.status_code == 200, changed.text
    assert changed.json()["created_by_name"] == "P1"
    assert changed.json()["updated_by_name"] == "P3"

    listed = client.get(
        f"/draft-series/match/{draft['match_id']}", headers=draft["captain_a"]
    )
    assert listed.json()[0]["updated_by_name"] == "P3"


def test_a_full_fixture_refuses_another_pairing(
    client: Client, draft: dict[str, Any]
) -> None:
    """The seeded event plays two series a round and the fixture holds both."""
    refused = client.post(
        "/draft-series", json=pairing(draft), headers=draft["captain_a"]
    )

    assert refused.status_code == 409, refused.text
    assert refused.json() == {
        "error": "This fixture already holds 2 series of the round"
    }


def test_a_replacing_pairing_does_not_count_against_the_round(
    client: Client, draft: dict[str, Any], seeded: dict[str, Any]
) -> None:
    """The open series pairs P2 and P4; the replacement keeps P2."""
    made = client.post(
        "/draft-series",
        json=pairing(draft, one=1, two=2)
        | {"replaces_series_id": seeded["series_open_id"]},
        headers=draft["captain_a"],
    )

    assert made.status_code == 201, made.text
    assert made.json()["replaces_series_id"] == seeded["series_open_id"]

    twice = client.post(
        "/draft-series",
        json=pairing(draft, one=1, two=2)
        | {"replaces_series_id": seeded["series_open_id"]},
        headers=draft["captain_a"],
    )
    assert twice.status_code == 409, twice.text
    assert twice.json() == {"error": "A draft already replaces this series"}


def test_a_replacement_names_an_open_series_and_keeps_a_player(
    client: Client, draft: dict[str, Any], seeded: dict[str, Any]
) -> None:
    scored = client.post(
        "/draft-series",
        json=pairing(draft, one=0, two=3)
        | {"replaces_series_id": seeded["series_played_id"]},
        headers=draft["captain_a"],
    )
    assert scored.status_code == 400, scored.text
    assert scored.json() == {"error": "A series that holds a result is not replaced"}

    strangers = client.post(
        "/draft-series",
        json=pairing(draft, one=0, two=2)
        | {"replaces_series_id": seeded["series_open_id"]},
        headers=draft["captain_a"],
    )
    assert strangers.status_code == 400, strangers.text
    assert strangers.json() == {"error": "A replacement keeps one of the two players"}


def test_publishing_a_replacement_swaps_the_series_in_one_action(
    client: Client,
    draft: dict[str, Any],
    seeded: dict[str, Any],
    auth_headers: dict[str, str],
) -> None:
    made = client.post(
        "/draft-series",
        json=pairing(draft, one=1, two=2)
        | {"replaces_series_id": seeded["series_open_id"]},
        headers=draft["captain_a"],
    )
    assert made.status_code == 201, made.text

    told = client.get(
        f"/draft-series/{made.json()['id']}/replaces", headers=draft["captain_a"]
    )
    assert told.status_code == 200, told.text
    assert told.json()["series_id"] == seeded["series_open_id"]
    assert told.json()["has_veto"] is False
    assert told.json()["has_result"] is False

    published = client.post(
        f"/draft-series/{made.json()['id']}/promote", headers=auth_headers
    )
    assert published.status_code == 201, published.text
    assert published.json()["player2_id"] == draft["players"][2]

    # SQLite hands the freed row id to the new series, so read the pairs
    from sqlmodel import col, select

    from app.core.db import Session
    from app.models.series import Series

    with Session() as session:
        rows = session.scalars(
            select(Series).where(col(Series.match_id) == draft["match_id"])
        ).all()
    players = draft["players"]
    assert {(row.player1_id, row.player2_id) for row in rows} == {
        (players[0], players[2]),
        (players[1], players[2]),
    }
    listed = client.get(
        f"/draft-series/match/{draft['match_id']}", headers=auth_headers
    )
    assert listed.json() == []


def test_a_replay_on_the_replaced_series_refuses_the_publish(
    client: Client,
    draft: dict[str, Any],
    seeded: dict[str, Any],
    auth_headers: dict[str, str],
) -> None:
    from app.core.db import Session
    from app.models.series_replay import DBSeriesReplay

    made = client.post(
        "/draft-series",
        json=pairing(draft, one=1, two=2)
        | {"replaces_series_id": seeded["series_open_id"]},
        headers=draft["captain_a"],
    )
    assert made.status_code == 201, made.text
    with Session.begin() as session:
        session.add(
            DBSeriesReplay(series_id=seeded["series_open_id"], game_no=1, key="a/b.w3g")
        )

    refused = client.post(
        f"/draft-series/{made.json()['id']}/promote", headers=auth_headers
    )

    assert refused.status_code == 409, refused.text
    assert refused.json() == {"error": "That series holds a replay"}
    assert client.get(f"/series/{seeded['series_open_id']}").status_code == 200
    assert (
        client.get(
            f"/draft-series/{made.json()['id']}", headers=auth_headers
        ).status_code
        == 200
    )


def test_a_ready_mark_belongs_to_the_own_team_and_clears_on_a_change(
    client: Client,
    draft: dict[str, Any],
    auth_headers: dict[str, str],
) -> None:
    widen(client, auth_headers, draft["season_id"])
    path = f"/draft-series/match/{draft['match_id']}/teams"

    plain = client.put(
        f"{path}/{draft['team_a']}/ready", json={"ready": True}, headers=draft["plain"]
    )
    assert plain.status_code == 403, plain.text

    crossed = client.put(
        f"{path}/{draft['team_b']}/ready",
        json={"ready": True},
        headers=draft["captain_a"],
    )
    assert crossed.status_code == 403, crossed.text

    marked = client.put(
        f"{path}/{draft['team_a']}/ready",
        json={"ready": True},
        headers=draft["captain_a"],
    )
    assert marked.status_code == 200, marked.text
    own = next(
        row for row in marked.json()["teams"] if row["team_id"] == draft["team_a"]
    )
    assert own["ready_by_name"] == "P1"
    assert own["ready_at"] is not None

    admin = client.put(
        f"{path}/{draft['team_b']}/ready", json={"ready": True}, headers=auth_headers
    )
    assert admin.status_code == 200, admin.text
    assert all(row["ready_at"] is not None for row in admin.json()["teams"])

    made = client.post("/draft-series", json=pairing(draft), headers=draft["captain_a"])
    assert made.status_code == 201, made.text
    state = client.get(
        f"/draft-series/match/{draft['match_id']}/state", headers=draft["captain_a"]
    )
    assert [row["ready_at"] for row in state.json()["teams"]] == [None, None]


def test_the_seen_stamp_is_written_by_its_own_call(
    client: Client, draft: dict[str, Any]
) -> None:
    """A read never writes: the page sends the seen call itself."""
    state = f"/draft-series/match/{draft['match_id']}/state"
    assert client.get(state, headers=draft["captain_a"]).json()["seen_at"] is None

    seen = client.put(
        f"/draft-series/match/{draft['match_id']}/teams/{draft['team_a']}/seen",
        headers=draft["captain_a"],
    )
    assert seen.status_code == 204, seen.text

    assert client.get(state, headers=draft["captain_a"]).json()["seen_at"] is not None
    # The other captain reads his own team's stamp, which is still unset
    assert client.get(state, headers=draft["captain_b"]).json()["seen_at"] is None


def test_the_working_mmr_difference_stands_in_front_of_the_stage(
    client: Client, draft: dict[str, Any], auth_headers: dict[str, str]
) -> None:
    state = f"/draft-series/match/{draft['match_id']}/state"
    first = client.get(state, headers=draft["captain_a"]).json()
    assert first["stage_max_mmr_difference"] == 100
    assert first["max_mmr_difference"] == 100

    set_250 = client.put(
        f"/draft-series/match/{draft['match_id']}/max-mmr-difference",
        json={"max_mmr_difference": 250},
        headers=draft["captain_b"],
    )
    assert set_250.status_code == 200, set_250.text
    assert set_250.json()["max_mmr_difference"] == 250
    assert set_250.json()["stage_max_mmr_difference"] == 100

    cleared = client.put(
        f"/draft-series/match/{draft['match_id']}/max-mmr-difference",
        json={"max_mmr_difference": None},
        headers=auth_headers,
    )
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["max_mmr_difference"] == 100

    refused = client.put(
        f"/draft-series/match/{draft['match_id']}/max-mmr-difference",
        json={"max_mmr_difference": 0},
        headers=draft["captain_a"],
    )
    assert refused.status_code == 422, refused.text


def test_a_plain_member_reads_no_draft_state(
    client: Client, draft: dict[str, Any]
) -> None:
    state = client.get(
        f"/draft-series/match/{draft['match_id']}/state", headers=draft["plain"]
    )

    assert state.status_code == 403, state.text
    assert state.json() == {"error": "Captains only"}
