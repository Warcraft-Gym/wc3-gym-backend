"""The map settings of a season: the ordered pool, the rules and the week maps.

A season names one rule per game of a series, and a week rule reads its map
from the playday. The pool is ordered, so the draft screens list it the way an
admin arranged it. A map also carries an uploaded picture.
"""

from typing import Any

import pytest
from httpx2 import Client

PNG = b"\x89PNG\r\n\x1a\n" + b"png body"
JPEG = b"\xff\xd8\xff\xe0" + b"jpeg body"


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


@pytest.mark.parametrize(
    "image,media_type",
    [(PNG, "image/png"), (JPEG, "image/jpeg"), (b"gif89a body", None)],
)
def test_a_map_carries_the_picture_that_was_uploaded_for_it(
    client: Client,
    seeded: dict[str, Any],
    auth_headers: dict[str, str],
    image: bytes,
    media_type: str | None,
) -> None:
    """The first bytes name the type; an unknown one is sent as plain bytes."""
    map_id = seeded["map_id"]
    resp = client.post(
        f"/maps/{map_id}/image",
        files={"image": ("map.bin", image)},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text

    resp = client.get(f"/maps/{map_id}/image")

    assert resp.status_code == 200, resp.text
    assert resp.content == image
    assert resp.headers["content-type"] == (media_type or "application/octet-stream")
    assert resp.headers["cache-control"] == "public, max-age=86400"


def test_a_client_that_holds_the_picture_is_told_it_is_unchanged(
    client: Client, seeded: dict[str, Any], auth_headers: dict[str, str]
) -> None:
    map_id = seeded["map_id"]
    client.post(
        f"/maps/{map_id}/image", files={"image": ("m.png", PNG)}, headers=auth_headers
    )
    etag = client.get(f"/maps/{map_id}/image").headers["etag"]

    resp = client.get(f"/maps/{map_id}/image", headers={"if-none-match": etag})
    assert resp.status_code == 304

    # A replaced picture is a new tag, so the client fetches it again
    client.post(
        f"/maps/{map_id}/image", files={"image": ("m.jpg", JPEG)}, headers=auth_headers
    )
    resp = client.get(f"/maps/{map_id}/image", headers={"if-none-match": etag})
    assert resp.status_code == 200
    assert resp.content == JPEG


def test_a_map_without_a_picture_has_none_to_fetch(
    client: Client, seeded: dict[str, Any]
) -> None:
    resp = client.get(f"/maps/{seeded['map_id']}/image")

    assert resp.status_code == 404, resp.text
    assert resp.json() == {"error": "Image not found"}
