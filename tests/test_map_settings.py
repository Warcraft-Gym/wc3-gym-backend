"""The map settings of a season: the ordered pool, the rules and the week maps.

A season names one rule per game of a series, and a week rule reads its map
from the playday. The pool is ordered, so the draft screens list it the way an
admin arranged it. The upload of a map picture is covered by test_map_picture.
"""

from typing import Any

import pytest
from httpx2 import Client


def pool(client: Client, season_id: int) -> list[str]:
    resp = client.get(f"/seasons/{season_id}")
    assert resp.status_code == 200, resp.text
    return [map["shortname"] for map in resp.json()["maps"]]


@pytest.fixture
def three_maps(
    client: Client, seeded: dict[str, Any], auth_headers: dict[str, str]
) -> list[int]:
    """The seeded map plus two more, all in the season pool, in that order."""
    ids = [seeded["map_id"]]
    for shortname in ("EI", "TS"):
        resp = client.post(
            "/maps",
            json={"name": shortname, "shortname": shortname},
            headers=auth_headers,
        )
        assert resp.status_code == 201, resp.text
        ids.append(resp.json()["id"])
    resp = client.post(
        f"/seasons/{seeded['season_id']}/maps",
        json={"map_ids": ids[1:]},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    return ids


def test_a_new_map_joins_the_pool_at_the_end(
    client: Client, seeded: dict[str, Any], three_maps: list[int]
) -> None:
    assert pool(client, seeded["season_id"]) == ["CH", "EI", "TS"]


def test_the_admin_reorders_the_pool(
    client: Client,
    seeded: dict[str, Any],
    three_maps: list[int],
    auth_headers: dict[str, str],
) -> None:
    season_id = seeded["season_id"]

    resp = client.put(
        f"/seasons/{season_id}/maps/order",
        json={"map_ids": list(reversed(three_maps))},
        headers=auth_headers,
    )

    assert resp.status_code == 200, resp.text
    assert [map["shortname"] for map in resp.json()["maps"]] == ["TS", "EI", "CH"]
    assert pool(client, season_id) == ["TS", "EI", "CH"]


def test_a_map_added_after_a_reorder_still_lands_last(
    client: Client,
    seeded: dict[str, Any],
    three_maps: list[int],
    auth_headers: dict[str, str],
) -> None:
    season_id = seeded["season_id"]
    client.put(
        f"/seasons/{season_id}/maps/order",
        json={"map_ids": list(reversed(three_maps))},
        headers=auth_headers,
    )
    resp = client.post(
        "/maps", json={"name": "LR", "shortname": "LR"}, headers=auth_headers
    )
    client.post(
        f"/seasons/{season_id}/maps",
        json={"map_ids": [resp.json()["id"]]},
        headers=auth_headers,
    )

    assert pool(client, season_id) == ["TS", "EI", "CH", "LR"]


@pytest.mark.parametrize("drop,add", [(1, None), (None, 999), (None, None)])
def test_an_order_that_is_not_the_whole_pool_is_refused(
    client: Client,
    seeded: dict[str, Any],
    three_maps: list[int],
    auth_headers: dict[str, str],
    drop: int | None,
    add: int | None,
) -> None:
    """Every map of the pool, once: no id left out, none added, none repeated."""
    map_ids = list(three_maps)
    if drop is not None:
        map_ids.pop(drop)
    elif add is not None:
        map_ids.append(add)
    else:
        map_ids[1] = map_ids[0]

    resp = client.put(
        f"/seasons/{seeded['season_id']}/maps/order",
        json={"map_ids": map_ids},
        headers=auth_headers,
    )

    assert resp.status_code == 400, resp.text
    assert "every map of the pool once" in resp.json()["error"]
    assert pool(client, seeded["season_id"]) == ["CH", "EI", "TS"]


@pytest.mark.parametrize("rules", ["week,loser,loser", "veto,veto,veto", "host"])
def test_a_season_takes_its_map_rules(
    client: Client, seeded: dict[str, Any], auth_headers: dict[str, str], rules: str
) -> None:
    resp = client.put(
        f"/seasons/{seeded['season_id']}",
        json={"map_rules": rules},
        headers=auth_headers,
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["map_rules"] == rules
    assert client.get(f"/seasons/{seeded['season_id']}").json()["map_rules"] == rules


@pytest.mark.parametrize("rules", ["ban", "week,ban", "week loser"])
def test_a_rule_the_season_does_not_know_is_refused(
    client: Client, seeded: dict[str, Any], auth_headers: dict[str, str], rules: str
) -> None:
    resp = client.put(
        f"/seasons/{seeded['season_id']}",
        json={"map_rules": rules},
        headers=auth_headers,
    )

    assert resp.status_code == 422, resp.text
    assert "is not a map rule" in resp.json()["error"]
    assert client.get(f"/seasons/{seeded['season_id']}").json()["map_rules"] is None


def test_the_admin_names_and_clears_the_map_of_a_week(
    client: Client,
    seeded: dict[str, Any],
    three_maps: list[int],
    auth_headers: dict[str, str],
) -> None:
    season_id = seeded["season_id"]

    resp = client.put(
        f"/seasons/{season_id}/week-maps",
        json={"playday": 2, "map_id": three_maps[1]},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["week_maps"] == [{"playday": 2, "map_id": three_maps[1]}]

    # A second write to the same week replaces the map
    client.put(
        f"/seasons/{season_id}/week-maps",
        json={"playday": 1, "map_id": three_maps[0]},
        headers=auth_headers,
    )
    resp = client.put(
        f"/seasons/{season_id}/week-maps",
        json={"playday": 2, "map_id": three_maps[2]},
        headers=auth_headers,
    )
    assert resp.json()["week_maps"] == [
        {"playday": 1, "map_id": three_maps[0]},
        {"playday": 2, "map_id": three_maps[2]},
    ]
    assert client.get(f"/seasons/{season_id}").json()["week_maps"] == [
        {"playday": 1, "map_id": three_maps[0]},
        {"playday": 2, "map_id": three_maps[2]},
    ]

    resp = client.put(
        f"/seasons/{season_id}/week-maps",
        json={"playday": 2, "map_id": None},
        headers=auth_headers,
    )
    assert resp.json()["week_maps"] == [{"playday": 1, "map_id": three_maps[0]}]


@pytest.mark.parametrize("playday", [0, 5, -1])
def test_a_week_outside_the_season_takes_no_map(
    client: Client,
    seeded: dict[str, Any],
    three_maps: list[int],
    auth_headers: dict[str, str],
    playday: int,
) -> None:
    """The seeded season runs four weeks."""
    resp = client.put(
        f"/seasons/{seeded['season_id']}/week-maps",
        json={"playday": playday, "map_id": three_maps[0]},
        headers=auth_headers,
    )

    assert resp.status_code == 400, resp.text
    assert resp.json() == {"error": "playday must be between 1 and 4"}


def test_a_map_leaving_the_pool_takes_its_week_with_it(
    client: Client,
    seeded: dict[str, Any],
    three_maps: list[int],
    auth_headers: dict[str, str],
) -> None:
    client.put(
        f"/seasons/{seeded['season_id']}/week-maps",
        json={"playday": 1, "map_id": three_maps[1]},
        headers=auth_headers,
    )

    resp = client.request(
        "DELETE",
        f"/seasons/{seeded['season_id']}/maps",
        json={"map_ids": [three_maps[1]]},
        headers=auth_headers,
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["week_maps"] == []


def test_a_map_outside_the_pool_is_not_a_week_map(
    client: Client, seeded: dict[str, Any], auth_headers: dict[str, str]
) -> None:
    outside = client.post(
        "/maps", json={"name": "LR", "shortname": "LR"}, headers=auth_headers
    ).json()["id"]

    resp = client.put(
        f"/seasons/{seeded['season_id']}/week-maps",
        json={"playday": 1, "map_id": outside},
        headers=auth_headers,
    )

    assert resp.status_code == 400, resp.text
    assert "not part of the season" in resp.json()["error"]


def test_a_map_without_a_picture_has_none_to_fetch(
    client: Client, seeded: dict[str, Any]
) -> None:
    resp = client.get(f"/maps/{seeded['map_id']}/image")

    assert resp.status_code == 404, resp.text
    assert resp.json() == {"error": "Image not found"}


def settings(
    client: Client, season_id: int, headers: dict[str, str], **body: str
) -> Any:  # noqa: ANN401  # a response
    return client.put(f"/seasons/{season_id}", json=body, headers=headers)


def test_the_games_take_the_picks_and_the_pool_allows_the_bans(
    client: Client,
    seeded: dict[str, Any],
    auth_headers: dict[str, str],
    three_maps: list[int],
) -> None:
    """Three veto games on a three map pool take three picks and allow no ban."""
    season_id = seeded["season_id"]
    ok = settings(
        client,
        season_id,
        auth_headers,
        map_rules="veto,veto,veto",
        pick_ban="Pick_A|Pick_B|Pick_A",
    )
    assert ok.status_code == 200, ok.text

    too_many_picks = settings(
        client, season_id, auth_headers, pick_ban="Pick_A|Pick_B|Pick_A|Pick_B"
    )
    assert too_many_picks.status_code == 400, too_many_picks.text
    assert too_many_picks.json()["error"] == "The games take 3 picks, the order has 4"

    too_many_bans = settings(
        client, season_id, auth_headers, pick_ban="Ban_A|Pick_A|Pick_B"
    )
    assert too_many_bans.status_code == 400, too_many_bans.text
    assert (
        too_many_bans.json()["error"]
        == "The pool allows 0 bans after 3 picks, the order has 1"
    )

    # A week game takes one map off the board and no pick; two loser games take two picks
    week = settings(
        client,
        season_id,
        auth_headers,
        map_rules="week,loser,loser",
        pick_ban="Pick_A|Pick_B",
    )
    assert week.status_code == 200, week.text
    over = settings(client, season_id, auth_headers, pick_ban="Ban_A|Pick_A|Pick_B")
    assert over.status_code == 400, over.text
    assert client.get(f"/seasons/{season_id}").json()["pick_ban"] == "Pick_A|Pick_B"


def test_a_step_the_board_does_not_know_is_refused(
    client: Client,
    seeded: dict[str, Any],
    auth_headers: dict[str, str],
    three_maps: list[int],
) -> None:
    resp = settings(client, seeded["season_id"], auth_headers, pick_ban="Ban_A|Ban_C")

    assert resp.status_code == 400, resp.text
    assert (
        resp.json()["error"]
        == "'Ban_C' is not a veto step. Valid steps are Ban_A, Ban_B, Pick_A, Pick_B."
    )


def test_a_map_the_order_needs_cannot_leave_the_pool(
    client: Client,
    seeded: dict[str, Any],
    auth_headers: dict[str, str],
    three_maps: list[int],
) -> None:
    season_id = seeded["season_id"]
    ok = settings(
        client,
        season_id,
        auth_headers,
        map_rules="veto,veto,veto",
        pick_ban="Ban_A|Pick_A|Pick_B",
    )
    assert ok.status_code == 400, ok.text
    ok = settings(
        client, season_id, auth_headers, map_rules="veto", pick_ban="Ban_A|Ban_B|Pick_A"
    )
    assert ok.status_code == 200, ok.text

    resp = client.request(
        "DELETE",
        f"/seasons/{season_id}/maps",
        json={"map_ids": three_maps[:1]},
        headers=auth_headers,
    )

    assert resp.status_code == 400, resp.text
    assert (
        resp.json()["error"] == "The pool allows 1 bans after 1 picks, the order has 2"
    )
    assert pool(client, season_id) == ["CH", "EI", "TS"]
