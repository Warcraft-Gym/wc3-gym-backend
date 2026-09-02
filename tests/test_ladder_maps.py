"""The ladder map import: match w3champions to warcraft3.info, then add.

warcraft3.info keeps every version of a map under its own name, so a match
by name alone picks the stale one: "Autumn Leaves v2" is "Autumn Leaves 2.0",
not "Autumn Leaves". The version decides, and when the display name carries
none the file path does.

The w3champions name is the truth: a map the app knows under an older name
or spelling of the same lineage is renamed in place, keeping its id and
short name; a missing picture is filled.
"""

from typing import Any

import pytest
import requests
from httpx2 import Client

from app.core.db import Session
from app.models.map import Map
from app.services import ladder_maps

PICTURE = b"\x89PNG\r\n\x1a\nmap picture"

LADDER = [
    {"id": 9, "name": "Twisted Meadows", "path": "W3Champions/9_TM_v1.1.w3x"},
    {
        "id": 1,
        "name": "Autumn Leaves v2",
        "path": "W3Champions/44_w3c_260615_2308_AutumnLeaves_v2.0.w3x",
    },
    {"id": 2, "name": "Echo Isles v2", "path": "W3Champions/2_EchoIsles_v2.2.w3x"},
    {"id": 3, "name": "Turtle Rock v2", "path": "W3Champions/3_TurtleRock_v2.0.w3x"},
    {"id": 4, "name": "Last Refuge", "path": "W3Champions/4_LastRefuge_v1.5.w3x"},
    {"id": 5, "name": "Nonesuch", "path": "W3Champions/5_Nonesuch_v1.0.w3x"},
]

MODES = [{"id": 2, "name": "2 vs 2", "maps": []}, {"id": 1, "name": "1 vs 1"}]


def entry(name: str, short: str, seen: str, file_name: str | None = None) -> dict:
    return {
        "name": name,
        "short": short,
        "image": {"file_name": file_name} if file_name else None,
        "map_files": [{"updated_at": seen}],
    }


MAP_DB = [
    entry("Autumn Leaves", "ALX", "2019-01-01T00:00:00Z", "old.png"),
    entry("Autumn Leaves 2.0", "AL", "2024-01-01T00:00:00Z", "autumn.png"),
    entry("Echo Isles", "EIX", "2018-01-01T00:00:00Z"),
    entry("Echo Isles 2.2", "EI2", "2023-01-01T00:00:00Z", "echo.png"),
    entry("Turtle Rock", "TRX", "2017-01-01T00:00:00Z"),
    entry("Turtle Rock 2.0", "TR2", "2022-01-01T00:00:00Z", "turtle.png"),
    entry("Last Refuge 1.2", "LRX", "2016-01-01T00:00:00Z"),
    entry("Last Refuge 1.5", "LR", "2020-01-01T00:00:00Z", "refuge.png"),
    entry("Twisted Meadows 1.1", "TM", "2021-01-01T00:00:00Z", "meadows.png"),
]


class FakeResponse:
    def __init__(self, body: Any, status_code: int = 200) -> None:  # noqa: ANN401  # a body of any source
        self.body = body
        self.status_code = status_code
        self.headers: dict[str, str] = {}
        self.text = "source is down"

    def json(self) -> Any:  # noqa: ANN401  # whatever the source answers
        return self.body

    @property
    def content(self) -> bytes:
        return self.body


@pytest.fixture
def sources(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Both sources and the picture host answer, and every url is logged."""
    called: list[str] = []
    modes = [MODES[0], MODES[1] | {"maps": LADDER}]

    def fake_request(
        self: requests.Session, method: str, url: str, **kwargs: object
    ) -> FakeResponse:
        called.append(url)
        if "active-modes" in url:
            return FakeResponse(modes)
        if "warcraft3.info" in url:
            return FakeResponse(MAP_DB)
        return FakeResponse(PICTURE)

    monkeypatch.setattr(requests.Session, "request", fake_request)
    return called


def rows(client: Client, season_id: int, headers: dict[str, str]) -> dict[str, dict]:
    resp = client.get(f"/seasons/{season_id}/maps/ladder-import", headers=headers)
    assert resp.status_code == 200, resp.text
    return {row["w3c_name"]: row for row in resp.json()}


def new_map(name: str, shortname: str) -> None:
    with Session.begin() as session:
        session.add(Map(name=name, shortname=shortname))


@pytest.mark.parametrize(
    ("ladder_name", "matched"),
    [
        ("Autumn Leaves v2", "Autumn Leaves 2.0"),
        ("Echo Isles v2", "Echo Isles 2.2"),
        ("Turtle Rock v2", "Turtle Rock 2.0"),
    ],
)
def test_a_renamed_map_matches_its_own_version(
    sources: list[str], ladder_name: str, matched: str
) -> None:
    """HARD GATE: matching on the name alone picks the stale map."""
    by_name = {row.w3c_name: row for row in ladder_maps.ladder_maps()}

    assert by_name[ladder_name].matched_name == matched


def test_the_path_names_the_version_the_display_name_leaves_out(
    sources: list[str],
) -> None:
    by_name = {row.w3c_name: row for row in ladder_maps.ladder_maps()}

    assert by_name["Last Refuge"].matched_name == "Last Refuge 1.5"


def test_a_map_warcraft3_info_does_not_know_stays_unmatched(
    sources: list[str],
) -> None:
    row = {row.w3c_name: row for row in ladder_maps.ladder_maps()}["Nonesuch"]

    assert (row.status, row.matched_name, row.shortname, row.image_url) == (
        "no_match",
        None,
        None,
        None,
    )


def test_the_preview_says_which_maps_the_season_already_plays(
    client: Client,
    seeded: dict[str, Any],
    auth_headers: dict[str, str],
    sources: list[str],
) -> None:
    # The stored name drifted from the ladder's, but it is the same lineage
    with Session.begin() as session:
        Map.update(session, seeded["map_id"], name="Autumn Leaves")

    listed = rows(client, seeded["season_id"], auth_headers)

    assert listed["Autumn Leaves v2"]["status"] == "in_pool"
    assert listed["Echo Isles v2"]["status"] == "new"
    assert listed["Echo Isles v2"]["shortname"] == "EI2"
    assert listed["Echo Isles v2"]["image_url"].endswith("/echo.png")
    assert listed["Nonesuch"]["status"] == "no_match"
    # The preview writes nothing, not even the rename
    assert [map["name"] for map in client.get("/maps").json()] == ["Autumn Leaves"]


def test_the_import_creates_the_maps_and_points_at_their_pictures(
    client: Client,
    seeded: dict[str, Any],
    auth_headers: dict[str, str],
    sources: list[str],
) -> None:
    season_id = seeded["season_id"]

    resp = client.post(
        f"/seasons/{season_id}/maps/ladder-import",
        json={"names": ["Echo Isles v2", "Nonesuch"]},
        headers=auth_headers,
    )

    assert resp.status_code == 200, resp.text
    pool = resp.json()["maps"]
    assert [map["name"] for map in pool] == [
        "Concealed Hill",
        "Echo Isles v2",
        "Nonesuch",
    ]
    # The match donates the short name; an unmatched map falls back to initials
    assert [map["shortname"] for map in pool] == ["CH", "EI2", "N"]
    # the picture is the url it is published at, not a copy of the bytes in the database
    icons = client.get(f"/maps/{pool[1]['id']}/image", follow_redirects=False)
    assert icons.status_code == 307
    assert icons.headers["location"].endswith("/echo.png")
    assert client.get(f"/maps/{pool[2]['id']}/image").status_code == 404


def test_the_import_keeps_a_known_map_and_fills_its_missing_picture(
    client: Client,
    seeded: dict[str, Any],
    auth_headers: dict[str, str],
    sources: list[str],
) -> None:
    with Session.begin() as session:
        Map.update(session, seeded["map_id"], name="Echo Isles v2")

    resp = client.post(
        f"/seasons/{seeded['season_id']}/maps/ladder-import",
        json={"names": ["Echo Isles v2", "Nonesuch"]},
        headers=auth_headers,
    )

    assert resp.status_code == 200, resp.text
    pool = resp.json()["maps"]
    assert [(map["id"], map["shortname"]) for map in pool] == [
        (seeded["map_id"], "CH"),
        (pool[1]["id"], "N"),
    ]
    icon = client.get(f"/maps/{seeded['map_id']}/image", follow_redirects=False)
    assert icon.status_code == 307
    assert icon.headers["location"].endswith("/echo.png")


def test_the_import_renames_a_drifted_map_instead_of_creating_a_twin(
    client: Client,
    seeded: dict[str, Any],
    auth_headers: dict[str, str],
    sources: list[str],
) -> None:
    """The app says "Echo Isles", the ladder "Echo Isles v2": one lineage."""
    new_map("Echo Isles", "EI")

    resp = client.post(
        f"/seasons/{seeded['season_id']}/maps/ladder-import",
        json={"names": ["Echo Isles v2"]},
        headers=auth_headers,
    )

    assert resp.status_code == 200, resp.text
    assert [(map["name"], map["shortname"]) for map in resp.json()["maps"]] == [
        ("Concealed Hill", "CH"),
        ("Echo Isles v2", "EI"),
    ]
    # Renamed in place: no twin row appeared
    assert sorted(map["name"] for map in client.get("/maps").json()) == [
        "Concealed Hill",
        "Echo Isles v2",
    ]


def test_a_map_with_its_picture_keeps_it_unfetched(
    client: Client,
    seeded: dict[str, Any],
    auth_headers: dict[str, str],
    sources: list[str],
) -> None:
    with Session.begin() as session:
        Map.update(session, seeded["map_id"], name="Echo Isles v2", icon=b"mine")

    resp = client.post(
        f"/seasons/{seeded['season_id']}/maps/ladder-import",
        json={"names": ["Echo Isles v2"]},
        headers=auth_headers,
    )

    assert resp.status_code == 200, resp.text
    assert client.get(f"/maps/{seeded['map_id']}/image").content == b"mine"
    assert not [url for url in sources if "cloudfront" in url]


def test_a_taken_short_name_falls_back_to_the_initials(
    client: Client,
    seeded: dict[str, Any],
    auth_headers: dict[str, str],
    sources: list[str],
) -> None:
    """Another map already holds AL, and the initials of the name too."""
    new_map("Alpine Lake", "AL")
    new_map("Amber Lagoon", "AL2")

    resp = client.post(
        f"/seasons/{seeded['season_id']}/maps/ladder-import",
        json={"names": ["Autumn Leaves v2"]},
        headers=auth_headers,
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["maps"][-1]["shortname"] == "AL3"


def test_a_source_that_is_down_answers_502(
    client: Client,
    seeded: dict[str, Any],
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_request(
        self: requests.Session, method: str, url: str, **kwargs: object
    ) -> FakeResponse:
        return FakeResponse(MODES, status_code=200 if "active-modes" in url else 503)

    monkeypatch.setattr(requests.Session, "request", fake_request)

    resp = client.get(
        f"/seasons/{seeded['season_id']}/maps/ladder-import", headers=auth_headers
    )

    assert resp.status_code == 502
    assert "error" in resp.json()
