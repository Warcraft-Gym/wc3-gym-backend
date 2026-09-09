"""A PUT that carries some fields leaves the others alone.

The update schemas mark every field optional and the services write only the fields the
request carries, so a field the body omits keeps its value.
"""

from typing import Any

from httpx2 import Client


def test_a_user_update_keeps_the_fields_it_was_not_given(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    user_id = seeded["player_ids"][0]
    before = client.get(f"/users/{user_id}").json()

    resp = client.put(f"/users/{user_id}", headers=auth_headers, json={"mmr": 2500})
    assert resp.status_code == 200, resp.text
    after = resp.json()

    assert after["mmr"] == 2500
    for field in ("name", "battleTag", "discordTag", "discordId", "race", "country"):
        assert after[field] == before[field], field


def test_a_season_update_keeps_the_fields_it_was_not_given(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    season_id = seeded["season_id"]
    before = client.get(f"/seasons/{season_id}").json()

    resp = client.put(
        f"/seasons/{season_id}", headers=auth_headers, json={"pick_ban": "Pick_A"}
    )
    assert resp.status_code == 200, resp.text
    after = resp.json()

    assert after["pick_ban"] == "Pick_A"
    for field in (
        "name",
        "round_count",
        "series_per_round",
        "start_date",
        "end_date",
    ):
        assert after[field] == before[field], field


def test_a_team_update_keeps_the_fields_it_was_not_given(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    team_id = seeded["team_a_id"]
    before = client.get(f"/teams/{team_id}").json()

    resp = client.put(
        f"/teams/{team_id}", headers=auth_headers, json={"long_name": "Alpha Club"}
    )
    assert resp.status_code == 200, resp.text
    after = resp.json()

    assert after["long_name"] == "Alpha Club"
    assert after["name"] == before["name"]
    assert after["seasons_info"] == before["seasons_info"]


def test_a_map_update_keeps_the_fields_it_was_not_given(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    map_id = seeded["map_id"]
    before = client.get(f"/maps/{map_id}").json()

    resp = client.put(
        f"/maps/{map_id}", headers=auth_headers, json={"shortname": "PMY"}
    )
    assert resp.status_code == 200, resp.text
    after = resp.json()

    assert after["shortname"] == "PMY"
    assert after["name"] == before["name"]
    assert after["image"] == before["image"]
