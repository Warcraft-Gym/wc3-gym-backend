"""The ladder map import: match w3champions to the map sources, then add.

warcraft3.info keeps every version of a map under its own name, so a match
by name alone picks the stale one: "Autumn Leaves v2" is "Autumn Leaves 2.0",
not "Autumn Leaves". The version decides, and when the display name carries
none the file path does.

The w3champions name is the truth: a map the app knows under an older name
or spelling of the same lineage is renamed in place, keeping its id and
short name; a missing picture is filled. A source is read only for a map that
is new or has no picture, and one that refuses hands over to the next.
"""

from collections.abc import Callable
from typing import Any

import pytest
import requests
from httpx2 import Client

from app.core.db import Session
from app.models.map import Map
from app.services import ladder_maps, map_sources
from app.services.map_sources.base import SourceMap

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


def entry(name: str, short: str, files: int, file_name: str | None = None) -> dict:
    return {
        "name": name,
        "short": short,
        "image": {"file_name": file_name} if file_name else None,
        "map_files_count": files,
    }


MAP_DB = [
    entry("Autumn Leaves", "ALX", 3, "old.png"),
    entry("Autumn Leaves 2.0", "AL", 8, "autumn.png"),
    entry("Echo Isles", "EIX", 2),
    # "Echo Isles v2" names no version here, so the most files decide
    entry("Echo Isles 2.2", "EI2", 7, "echo.png"),
    entry("Turtle Rock", "TRX", 1),
    entry("Turtle Rock 2.0", "TR2", 6, "turtle.png"),
    entry("Last Refuge 1.2", "LRX", 1),
    entry("Last Refuge 1.5", "LR", 4, "refuge.png"),
    entry("Twisted Meadows 1.1", "TM", 5, "meadows.png"),
    # Off the ladder this season, but warcraft3.info still has the picture
    entry("War Hail", "WH", 4, "warhail.png"),
]

# Liquipedia's pages: the title, the players its category names, and its infobox picture
WIKI_PAGES = {
    "Echo Isles": (2, "Wc3EchoIsles.png"),
    "Turtle Rock": (2, "Wc3TurtleRock.png"),
}
WIKI_FILES = "https://liquipedia.net/commons/images/"


def wiki_answer(params: dict[str, str], pages: dict[str, tuple[int, str]]) -> dict:
    """What Liquipedia's API answers a query about these pages."""
    if params.get("generator") == "categorymembers":
        found = [
            {
                "title": title,
                "categories": [
                    {"title": "Category:Maps"},
                    {"title": f"Category:Maps ({players} Players)"},
                ],
            }
            for title, (players, _) in pages.items()
        ]
    elif params.get("prop") == "revisions":
        found = [
            {
                "title": title,
                "revisions": [
                    {
                        "slots": {
                            "main": {
                                "content": "{{Infobox map\n"
                                f"|name={title}\n|image={pages[title][1]}\n|players=2\n}}}}"
                            }
                        }
                    }
                ],
            }
            for title in params["titles"].split("|")
        ]
    else:
        found = [
            {"title": title, "imageinfo": [{"url": f"{WIKI_FILES}{title[5:]}"}]}
            for title in params["titles"].split("|")
        ]
    return {"query": {"pages": found}}


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


def answer_with(
    monkeypatch: pytest.MonkeyPatch,
    map_db: FakeResponse,
    wiki_pages: dict[str, tuple[int, str]] | None = None,
) -> list[str]:
    """w3champions answers, each source as named, and every url is logged. With no
    pages named, Liquipedia cannot be read."""
    called: list[str] = []
    modes = [MODES[0], MODES[1] | {"maps": LADDER}]

    def fake_request(
        self: requests.Session,
        method: str,
        url: str,
        params: dict[str, str] | None = None,
        **kwargs: object,
    ) -> FakeResponse:
        called.append(url)
        if "active-modes" in url:
            return FakeResponse(modes)
        if "warcraft3.info" in url:
            return map_db
        if "api.php" in url:
            if wiki_pages is None:
                return FakeResponse({}, status_code=503)
            return FakeResponse(wiki_answer(params or {}, wiki_pages))
        return FakeResponse(PICTURE)

    monkeypatch.setattr(requests.Session, "request", fake_request)
    return called


@pytest.fixture
def sources(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """warcraft3.info answers, and Liquipedia knows none of its maps."""
    return answer_with(monkeypatch, FakeResponse(MAP_DB), wiki_pages={})


def matches() -> dict[str, SourceMap]:
    """What warcraft3.info holds for each ladder map."""
    names = ladder_maps.ladder_names()
    found = map_sources.SOURCES["warcraft3_info"].find(list(names.values()))
    return {name: found[lookup] for name, lookup in names.items() if lookup in found}


def rows(client: Client, season_id: int, headers: dict[str, str]) -> dict[str, dict]:
    resp = client.get(f"/events/{season_id}/maps/ladder-import", headers=headers)
    assert resp.status_code == 200, resp.text
    return {row["w3c_name"]: row for row in resp.json()}


def new_map(name: str, shortname: str) -> None:
    with Session.begin() as session:
        session.add(Map(name=name, shortname=shortname))


def picture_the_ladder() -> None:
    """The app holds every ladder map, each with a picture of its own."""
    with Session.begin() as session:
        for number, ladder_map in enumerate(LADDER):
            session.add(
                Map(
                    name=str(ladder_map["name"]),
                    shortname=f"M{number}",
                    image=f"https://example.test/{number}.png",
                )
            )


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
    assert matches()[ladder_name].name == matched


def test_the_path_names_the_version_the_display_name_leaves_out(
    sources: list[str],
) -> None:
    assert matches()["Last Refuge"].name == "Last Refuge 1.5"


def test_a_map_warcraft3_info_does_not_know_stays_unmatched(
    sources: list[str],
) -> None:
    assert "Nonesuch" not in matches()


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
        f"/events/{season_id}/maps/ladder-import",
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
        f"/events/{seeded['season_id']}/maps/ladder-import",
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
        f"/events/{seeded['season_id']}/maps/ladder-import",
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


def test_a_map_with_its_picture_keeps_it(
    client: Client,
    seeded: dict[str, Any],
    auth_headers: dict[str, str],
    sources: list[str],
) -> None:
    """A picture an admin uploaded is not replaced by the one the ladder matched."""
    mine = "https://test.public.blob.vercel-storage.com/maps/1-0.png"
    with Session.begin() as session:
        Map.update(session, seeded["map_id"], name="Echo Isles v2", image=mine)

    resp = client.post(
        f"/events/{seeded['season_id']}/maps/ladder-import",
        json={"names": ["Echo Isles v2"]},
        headers=auth_headers,
    )

    assert resp.status_code == 200, resp.text
    icon = client.get(f"/maps/{seeded['map_id']}/image", follow_redirects=False)
    assert icon.headers["location"] == mine


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
        f"/events/{seeded['season_id']}/maps/ladder-import",
        json={"names": ["Autumn Leaves v2"]},
        headers=auth_headers,
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["maps"][-1]["shortname"] == "AL3"


def test_w3champions_down_answers_502(
    client: Client,
    seeded: dict[str, Any],
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Without the ladder there is nothing to import."""

    def fake_request(
        self: requests.Session, method: str, url: str, **kwargs: object
    ) -> FakeResponse:
        return FakeResponse(MAP_DB, status_code=503 if "active-modes" in url else 200)

    monkeypatch.setattr(requests.Session, "request", fake_request)

    resp = client.get(
        f"/events/{seeded['season_id']}/maps/ladder-import", headers=auth_headers
    )

    assert resp.status_code == 502
    assert "error" in resp.json()


def test_no_source_is_read_when_every_ladder_map_has_its_picture(
    client: Client,
    seeded: dict[str, Any],
    auth_headers: dict[str, str],
    sources: list[str],
) -> None:
    with Session.begin() as session:
        Map.update(session, seeded["map_id"], image="https://example.test/hill.png")
    picture_the_ladder()

    listed = client.get("/maps/ladder-import", headers=auth_headers).json()
    resp = client.post(
        "/maps/ladder-import",
        json={"names": [row["w3c_name"] for row in listed]},
        headers=auth_headers,
    )

    assert resp.status_code == 200, resp.text
    assert {row["status"] for row in listed} == {"known"}
    # each row shows the picture and the name the app holds, with nothing read
    assert listed[0]["image_url"] == "https://example.test/0.png"
    assert listed[0]["matched_name"] == LADDER[0]["name"]
    assert not [url for url in sources if "active-modes" not in url]


def test_only_a_map_without_a_picture_is_looked_up(
    client: Client,
    seeded: dict[str, Any],
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    picture_the_ladder()
    asked: list[list[str]] = []
    warcraft3_info = map_sources.SOURCES["warcraft3_info"]
    monkeypatch.setattr(
        warcraft3_info, "find", lambda names: asked.append(names) or {}, raising=False
    )
    answer_with(monkeypatch, FakeResponse(MAP_DB), wiki_pages={})
    new_map("Unlisted Plains", "UP")

    resp = client.get("/maps/ladder-import", headers=auth_headers)

    assert resp.status_code == 200, resp.text
    assert asked == [["Concealed Hill", "Unlisted Plains"]]


def test_a_refused_read_goes_on_with_liquipedia_and_copies_its_pictures(
    client: Client,
    seeded: dict[str, Any],
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    blob_store: dict[str, bytes],
) -> None:
    """warcraft3.info challenges the backend. Liquipedia's pictures land in our store."""
    pages = WIKI_PAGES | {"Plain Page": (2, "Plain.png")}
    answer_with(monkeypatch, FakeResponse("challenge", status_code=403), pages)
    new_map("Plain Page", "PP")

    listed = {
        row["w3c_name"]: row
        for row in client.get("/maps/ladder-import", headers=auth_headers).json()
    }

    assert listed["Echo Isles v2"]["status"] == "new"
    assert listed["Echo Isles v2"]["source"] == "Liquipedia"
    assert listed["Echo Isles v2"]["matched_name"] == "Echo Isles"
    # the wiki refuses its files to a page on another site, so the picture shows once it is ours
    assert listed["Echo Isles v2"]["image_url"] is None
    # no source holds a short name now, so the map shows the initials it will get
    assert listed["Echo Isles v2"]["shortname"] == "EI"
    assert listed["Echo Isles v2"]["unreached"] == ["warcraft3.info"]
    assert listed["Nonesuch"]["status"] == "no_match"
    # a map off the ladder is still offered, though its picture shows only once it is ours
    assert listed["Plain Page"]["status"] == "off_ladder"
    assert listed["Plain Page"]["image_url"] is None

    resp = client.post(
        "/maps/ladder-import",
        json={"names": ["Echo Isles v2", "Nonesuch", "Plain Page"]},
        headers=auth_headers,
    )

    assert resp.status_code == 200, resp.text
    imported = {map["name"]: map for map in resp.json()}
    assert imported["Echo Isles v2"]["image"] in blob_store
    assert imported["Plain Page"]["image"] in blob_store
    assert blob_store[imported["Echo Isles v2"]["image"]] == PICTURE
    assert imported["Nonesuch"]["image"] is None


def test_every_source_down_still_imports_with_initials_and_no_pictures(
    client: Client,
    seeded: dict[str, Any],
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    answer_with(monkeypatch, FakeResponse("challenge", status_code=403))

    listed = {
        row["w3c_name"]: row
        for row in client.get("/maps/ladder-import", headers=auth_headers).json()
    }

    assert listed["Echo Isles v2"]["status"] == "no_match"
    assert listed["Echo Isles v2"]["unreached"] == ["warcraft3.info", "Liquipedia"]

    resp = client.post(
        "/maps/ladder-import", json={"names": ["Echo Isles v2"]}, headers=auth_headers
    )

    assert resp.status_code == 200, resp.text
    assert [(map["name"], map["shortname"], map["image"]) for map in resp.json()] == [
        ("Echo Isles v2", "EI", None)
    ]


def test_the_global_preview_says_which_maps_the_app_knows(
    client: Client,
    seeded: dict[str, Any],
    auth_headers: dict[str, str],
    sources: list[str],
) -> None:
    """The maps page has no pool: a map the app holds under an older name is known."""
    with Session.begin() as session:
        Map.update(session, seeded["map_id"], name="Autumn Leaves")
    new_map("Echo Isles", "EI")

    resp = client.get("/maps/ladder-import", headers=auth_headers)

    assert resp.status_code == 200, resp.text
    listed = {row["w3c_name"]: row for row in resp.json()}
    assert listed["Autumn Leaves v2"]["status"] == "known"
    assert listed["Echo Isles v2"]["status"] == "known"
    assert listed["Turtle Rock v2"]["status"] == "new"
    # a known map names the map of the app it is, so a cup pool can take it
    assert listed["Autumn Leaves v2"]["map_id"] == seeded["map_id"]
    assert listed["Turtle Rock v2"]["map_id"] is None
    assert listed["Nonesuch"]["status"] == "no_match"
    # The season preview still tells its pool apart from the rest the app knows
    season = rows(client, seeded["season_id"], auth_headers)
    assert season["Autumn Leaves v2"]["status"] == "in_pool"
    assert season["Echo Isles v2"]["status"] == "known"


def test_an_organizer_imports_the_ladder_maps_and_nothing_else(
    client: Client,
    seeded: dict[str, Any],
    auth_headers: dict[str, str],
    member: Callable[..., dict[str, str]],
    sources: list[str],
) -> None:
    """A cup's organizer brings in the ladder maps the app lacks, and a name off
    the ladder is left alone."""
    from tests.test_event_organizers import grant

    grant(client, auth_headers, "77")
    headers = member("77")

    resp = client.post(
        "/maps/ladder-import",
        json={"names": ["Turtle Rock v2", "Concealed Hill"]},
        headers=headers,
    )

    assert resp.status_code == 200, resp.text
    assert [row["name"] for row in resp.json()] == ["Turtle Rock v2"]
    # the map is tagged with the ladder it came from
    assert resp.json()[0]["modes"] == "1v1"
    listed = {
        row["w3c_name"]: row
        for row in client.get("/maps/ladder-import", headers=headers).json()
    }
    assert listed["Turtle Rock v2"]["map_id"] is not None
    # a member who organizes nothing imports nothing
    assert (
        client.post(
            "/maps/ladder-import", json={"names": []}, headers=member("78")
        ).status_code
        == 403
    )


def test_the_global_import_renames_and_pictures_without_touching_a_pool(
    client: Client,
    seeded: dict[str, Any],
    auth_headers: dict[str, str],
    sources: list[str],
) -> None:
    new_map("Echo Isles", "EI")

    resp = client.post(
        "/maps/ladder-import",
        json={"names": ["Echo Isles v2", "Nonesuch"]},
        headers=auth_headers,
    )

    assert resp.status_code == 200, resp.text
    imported = resp.json()
    assert [(map["name"], map["shortname"]) for map in imported] == [
        ("Echo Isles v2", "EI"),
        ("Nonesuch", "N"),
    ]
    assert imported[0]["image"].endswith("/echo.png")
    # Renamed in place, and the season pool is what it was
    assert sorted(map["name"] for map in client.get("/maps").json()) == [
        "Concealed Hill",
        "Echo Isles v2",
        "Nonesuch",
    ]
    pool = client.get(f"/events/{seeded['season_id']}").json()["maps"]
    assert [map["name"] for map in pool] == ["Concealed Hill"]


def test_the_preview_shows_the_short_name_a_map_will_have(
    client: Client,
    seeded: dict[str, Any],
    auth_headers: dict[str, str],
    sources: list[str],
) -> None:
    """A known map keeps its own short name; a new one gets the one the import assigns."""
    new_map("Echo Isles", "EI")
    new_map("Turtle Rock", "TR2")

    resp = client.get("/maps/ladder-import", headers=auth_headers)

    assert resp.status_code == 200, resp.text
    listed = {row["w3c_name"]: row for row in resp.json()}
    assert (
        listed["Echo Isles v2"]["status"],
        listed["Echo Isles v2"]["shortname"],
    ) == ("known", "EI")
    assert (
        listed["Turtle Rock v2"]["status"],
        listed["Turtle Rock v2"]["shortname"],
    ) == ("known", "TR2")
    # Nonesuch has no match and no donated short name: the initials it will get
    assert listed["Nonesuch"]["shortname"] == "N"


def test_a_map_off_the_ladder_lists_with_the_picture_warcraft3_info_has(
    client: Client,
    seeded: dict[str, Any],
    auth_headers: dict[str, str],
    sources: list[str],
) -> None:
    new_map("War Hail", "WH")
    new_map("Nowhere", "NW")

    resp = client.get("/maps/ladder-import", headers=auth_headers)

    assert resp.status_code == 200, resp.text
    listed = {row["w3c_name"]: row for row in resp.json()}
    assert listed["War Hail"]["status"] == "off_ladder"
    assert listed["War Hail"]["shortname"] == "WH"
    assert listed["War Hail"]["image_url"].endswith("/warhail.png")
    # No picture anywhere for Nowhere, and Concealed Hill is not in the fake map db
    assert "Nowhere" not in listed
    assert "Concealed Hill" not in listed

    resp = client.post(
        "/maps/ladder-import", json={"names": ["War Hail"]}, headers=auth_headers
    )

    assert resp.status_code == 200, resp.text
    assert [(map["name"], map["shortname"]) for map in resp.json()] == [
        ("War Hail", "WH")
    ]
    assert resp.json()[0]["image"].endswith("/warhail.png")
    # Once pictured it is no longer offered
    listed = {
        row["w3c_name"]
        for row in client.get("/maps/ladder-import", headers=auth_headers).json()
    }
    assert "War Hail" not in listed


def test_a_map_names_the_modes_it_is_played_as(
    client: Client, seeded: dict[str, Any], auth_headers: dict[str, str]
) -> None:
    """The modes read back each once, in their own order; an unknown one is refused."""
    map_id = seeded["map_id"]
    resp = client.put(
        f"/maps/{map_id}",
        json={"modes": ["ffa", "2v2", "1v1", "2v2"]},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["modes"] == "1v1,2v2,ffa"
    refused = client.put(f"/maps/{map_id}", json={"modes": "7v7"}, headers=auth_headers)
    assert refused.status_code == 422
