"""The sites an admin takes maps from, and how each of them is read.

A fake source stands in for a site in the route tests, so they hold for any site
the registry gains. The two real sources are read against faked answers.
"""

from collections.abc import Callable
from dataclasses import dataclass, field
from typing import Any

import pytest
import requests
import vercel.oidc
from httpx2 import Client, Response

from app.core.db import Session
from app.core.exceptions import ExternalServiceError
from app.models.map import Map
from app.services import blob, map_sources
from app.services import maps as map_service
from app.services.map_sources import base, liquipedia
from app.services.map_sources.base import SourceMap, matching
from app.services.maps import MapService
from tests.test_ladder_maps import (
    PICTURE,
    WIKI_FILES,
    WIKI_PAGES,
    FakeResponse,
    wiki_answer,
)
from tests.test_team_logo import REAL_PUT_ICON

PUBLISHED = "https://pictures.test/"


@dataclass
class FakeSource:
    maps: list[SourceMap] = field(default_factory=list)
    copies_pictures: bool = True
    down: bool = False
    key: str = "fake"
    title: str = "Fake maps"
    credit_url: str = "https://fake.test/maps"
    license: str | None = "CC-0"

    def catalogue(self, q: str) -> list[SourceMap]:
        if self.down:
            raise ExternalServiceError("fake.test answered 403")
        return matching(self.maps, q)

    def find(self, names: list[str]) -> dict[str, SourceMap]:
        if self.down:
            raise ExternalServiceError("fake.test answered 403")
        return {row.name: row for row in self.maps if row.name in names}


@pytest.fixture
def source(monkeypatch: pytest.MonkeyPatch) -> FakeSource:
    fake = FakeSource(
        maps=[
            SourceMap(
                name="Amber Lagoon",
                players=4,
                modes="2v2",
                shortname="AML",
                picture_url=f"{PUBLISHED}amber.png",
            ),
            SourceMap(name="Bleak Harbor", players=2, modes="1v1"),
            SourceMap(
                name="Concealed Hill", players=2, picture_url=f"{PUBLISHED}hill.png"
            ),
        ]
    )
    monkeypatch.setitem(map_sources.SOURCES, "fake", fake)
    return fake


@pytest.fixture
def pictures(monkeypatch: pytest.MonkeyPatch) -> list[str]:
    """Every picture host answers a PNG, and every url it was asked for is logged."""
    called: list[str] = []

    def fake_request(
        self: requests.Session, method: str, url: str, **kwargs: object
    ) -> FakeResponse:
        called.append(url)
        return FakeResponse(PICTURE)

    monkeypatch.setattr(requests.Session, "request", fake_request)
    return called


def pick(
    client: Client, headers: dict[str, str], *maps: dict[str, Any], key: str = "fake"
) -> Response:
    return client.post(f"/maps/sources/{key}", json={"maps": maps}, headers=headers)


def test_an_admin_sees_each_source_with_its_credit(
    client: Client,
    seeded: dict[str, Any],
    auth_headers: dict[str, str],
    source: FakeSource,
) -> None:
    resp = client.get("/maps/sources", headers=auth_headers)

    assert resp.status_code == 200, resp.text
    by_key = {row["key"]: row for row in resp.json()}
    assert set(by_key) == {"warcraft3_info", "liquipedia", "fake"}
    assert by_key["liquipedia"]["license"] == "CC-BY-SA 3.0"
    assert by_key["fake"] == {
        "key": "fake",
        "title": "Fake maps",
        "credit_url": "https://fake.test/maps",
        "license": "CC-0",
    }


def test_a_list_searches_and_says_which_maps_the_app_holds(
    client: Client,
    seeded: dict[str, Any],
    auth_headers: dict[str, str],
    source: FakeSource,
) -> None:
    with Session.begin() as session:
        lineage = Map(name="Bleak Harbor v3", shortname="BH", image="mine.png")
        session.add(lineage)
        session.flush()
        lineage_id = lineage.id

    rows = client.get("/maps/sources/fake", headers=auth_headers).json()

    # a list is by name; the seeded Concealed Hill is held, and has no picture
    assert [row["name"] for row in rows] == [
        "Amber Lagoon",
        "Bleak Harbor",
        "Concealed Hill",
    ]
    assert (rows[0]["map_id"], rows[0]["pictured"]) == (None, False)
    assert rows[0]["players"] == 4
    assert (rows[1]["map_id"], rows[1]["pictured"]) == (lineage_id, True)
    assert (rows[2]["map_id"], rows[2]["pictured"]) == (seeded["map_id"], False)

    found = client.get("/maps/sources/fake?q=hArB", headers=auth_headers).json()

    assert [row["name"] for row in found] == ["Bleak Harbor"]


def test_a_name_the_table_cannot_hold_is_not_offered(
    client: Client,
    seeded: dict[str, Any],
    auth_headers: dict[str, str],
    source: FakeSource,
) -> None:
    source.maps = [SourceMap(name="x" * 51), SourceMap(name="y" * 50)]

    rows = client.get("/maps/sources/fake", headers=auth_headers).json()

    assert [row["name"] for row in rows] == ["y" * 50]


def test_an_import_makes_each_map_with_the_chosen_modes_and_copies_its_picture(
    client: Client,
    seeded: dict[str, Any],
    auth_headers: dict[str, str],
    source: FakeSource,
    pictures: list[str],
    blob_store: dict[str, bytes],
) -> None:
    resp = pick(
        client,
        auth_headers,
        {"name": "Amber Lagoon", "modes": ["ffa", "2v2"]},
        {"name": "Bleak Harbor", "modes": "custom"},
    )

    assert resp.status_code == 200, resp.text
    amber, bleak = resp.json()
    # the source's short name, else the initials; the modes as the app reads them
    assert (amber["name"], amber["shortname"], amber["modes"]) == (
        "Amber Lagoon",
        "AML",
        "2v2,ffa",
    )
    assert (bleak["name"], bleak["shortname"], bleak["modes"]) == (
        "Bleak Harbor",
        "BH",
        "custom",
    )
    assert pictures == [f"{PUBLISHED}amber.png"]
    assert blob_store[amber["image"]] == PICTURE
    assert blob.ours(amber["image"])
    assert bleak["image"] is None


def test_a_source_that_does_not_copy_keeps_the_url_it_publishes(
    client: Client,
    seeded: dict[str, Any],
    auth_headers: dict[str, str],
    source: FakeSource,
    pictures: list[str],
    blob_store: dict[str, bytes],
) -> None:
    source.copies_pictures = False

    resp = pick(client, auth_headers, {"name": "Amber Lagoon", "modes": "2v2"})

    assert resp.status_code == 200, resp.text
    assert resp.json()[0]["image"] == f"{PUBLISHED}amber.png"
    assert pictures == []
    assert blob_store == {}


def test_a_known_map_gains_the_modes_and_keeps_its_name_and_picture(
    client: Client,
    seeded: dict[str, Any],
    auth_headers: dict[str, str],
    source: FakeSource,
    pictures: list[str],
) -> None:
    """The source's picture does not replace one the map already has."""
    source.maps.append(SourceMap(name="Harbor", picture_url=f"{PUBLISHED}harbor.png"))
    with Session.begin() as session:
        session.add(
            Map(name="Harbor v2", shortname="HB", image="mine.png", modes="1v1")
        )

    resp = pick(client, auth_headers, {"name": "Harbor", "modes": "2v2"})

    assert resp.status_code == 200, resp.text
    assert [
        (row["name"], row["shortname"], row["image"], row["modes"])
        for row in resp.json()
    ] == [("Harbor v2", "HB", "mine.png", "1v1,2v2")]
    assert pictures == []


def test_a_known_map_without_a_picture_gets_the_source_one(
    client: Client,
    seeded: dict[str, Any],
    auth_headers: dict[str, str],
    source: FakeSource,
    pictures: list[str],
    blob_store: dict[str, bytes],
) -> None:
    resp = pick(client, auth_headers, {"name": "Concealed Hill", "modes": "1v1"})

    assert resp.status_code == 200, resp.text
    assert resp.json()[0]["id"] == seeded["map_id"]
    assert resp.json()[0]["image"] in blob_store


@pytest.mark.parametrize(
    "answer",
    [
        FakeResponse(b"", status_code=404),
        FakeResponse(b"GIF89a not a picture we store"),
        FakeResponse(b"\x89PNG\r\n\x1a\n" + b"0" * (blob.MAX_ICON_BYTES + 1)),
    ],
    ids=["gone", "another-format", "too-large"],
)
def test_a_picture_that_cannot_be_copied_leaves_the_map_without_one(
    client: Client,
    seeded: dict[str, Any],
    auth_headers: dict[str, str],
    source: FakeSource,
    monkeypatch: pytest.MonkeyPatch,
    answer: FakeResponse,
) -> None:
    monkeypatch.setattr(
        requests.Session, "request", lambda self, method, url, **kwargs: answer
    )

    resp = pick(client, auth_headers, {"name": "Amber Lagoon", "modes": "2v2"})

    assert resp.status_code == 200, resp.text
    assert resp.json()[0]["image"] is None


def test_a_store_that_cannot_be_written_leaves_the_map_without_a_picture(
    client: Client,
    seeded: dict[str, Any],
    auth_headers: dict[str, str],
    source: FakeSource,
    pictures: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The maps are already committed, so the store failing does not undo the import."""

    def no_token() -> str:
        raise vercel.oidc.VercelOidcTokenError("no token")

    monkeypatch.setattr(blob, "put_icon", REAL_PUT_ICON)
    monkeypatch.setattr(vercel.oidc, "get_vercel_oidc_token", no_token)

    resp = pick(client, auth_headers, {"name": "Amber Lagoon", "modes": "2v2"})

    assert resp.status_code == 200, resp.text
    assert resp.json()[0]["image"] is None


def test_copying_stops_in_time_and_the_next_import_goes_on(
    client: Client,
    seeded: dict[str, Any],
    auth_headers: dict[str, str],
    source: FakeSource,
    pictures: list[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A long list of pictures must not outrun the function's time limit."""
    monkeypatch.setattr(map_service, "COPY_SECONDS", -1)

    first = pick(client, auth_headers, {"name": "Amber Lagoon", "modes": "2v2"})

    assert first.status_code == 200, first.text
    assert first.json()[0]["image"] is None
    assert pictures == []

    monkeypatch.setattr(map_service, "COPY_SECONDS", 40)
    second = pick(client, auth_headers, {"name": "Amber Lagoon", "modes": "2v2"})

    assert second.json()[0]["id"] == first.json()[0]["id"]
    assert second.json()[0]["image"] is not None


def test_an_upload_made_during_the_copy_wins(
    seeded: dict[str, Any], blob_store: dict[str, bytes]
) -> None:
    MapService().update_icon(seeded["map_id"], PICTURE)
    uploaded = next(iter(blob_store))

    MapService().update_icon(seeded["map_id"], PICTURE + b"copy", keep_existing=True)

    assert MapService().get_image_url(seeded["map_id"]) == uploaded
    assert list(blob_store) == [uploaded]


def test_a_call_takes_at_most_ten_maps(
    client: Client,
    seeded: dict[str, Any],
    auth_headers: dict[str, str],
    source: FakeSource,
) -> None:
    maps = [{"name": f"Map {number}", "modes": "1v1"} for number in range(11)]

    assert pick(client, auth_headers, *maps).status_code == 422
    assert pick(client, auth_headers).status_code == 422


def test_an_unknown_mode_is_refused(
    client: Client,
    seeded: dict[str, Any],
    auth_headers: dict[str, str],
    source: FakeSource,
) -> None:
    resp = pick(client, auth_headers, {"name": "Amber Lagoon", "modes": "7v7"})

    assert resp.status_code == 422


def test_a_member_who_organizes_nothing_reads_and_imports_nothing(
    client: Client,
    seeded: dict[str, Any],
    member: Callable[..., dict[str, str]],
    source: FakeSource,
) -> None:
    headers = member("71")

    assert client.get("/maps/sources", headers=headers).status_code == 403
    assert client.get("/maps/sources/fake", headers=headers).status_code == 403
    assert pick(client, headers, {"name": "Amber Lagoon"}).status_code == 403


def test_an_organizer_adds_the_maps_it_picks_and_touches_no_other(
    client: Client,
    seeded: dict[str, Any],
    auth_headers: dict[str, str],
    member: Callable[..., dict[str, str]],
    source: FakeSource,
    pictures: list[str],
    blob_store: dict[str, bytes],
) -> None:
    from tests.test_event_organizers import grant

    grant(client, auth_headers, "72")
    headers = member("72")

    assert client.get("/maps/sources", headers=headers).status_code == 200
    listed = client.get("/maps/sources/fake", headers=headers)
    assert listed.json()[0]["name"] == "Amber Lagoon"

    resp = pick(client, headers, {"name": "Amber Lagoon", "modes": "2v2"})

    assert resp.status_code == 200, resp.text
    amber = resp.json()[0]
    assert (amber["name"], amber["modes"]) == ("Amber Lagoon", "2v2")
    assert amber["image"] in blob_store
    # the seeded map, which the source also knows, was not picked
    held = client.get(f"/maps/{seeded['map_id']}").json()
    assert (held["image"], held["modes"]) == (None, None)
    # the rest of the map list stays the admins'
    made = client.post("/maps", json={"name": "Mine"}, headers=headers)
    assert made.status_code == 403


def test_an_unknown_source_answers_404(
    client: Client, seeded: dict[str, Any], auth_headers: dict[str, str]
) -> None:
    assert client.get("/maps/sources/nowhere", headers=auth_headers).status_code == 404
    resp = pick(client, auth_headers, {"name": "Amber Lagoon"}, key="nowhere")
    assert resp.status_code == 404


def test_a_source_that_cannot_be_read_answers_502_and_writes_nothing(
    client: Client,
    seeded: dict[str, Any],
    auth_headers: dict[str, str],
    source: FakeSource,
) -> None:
    source.down = True

    listed = client.get("/maps/sources/fake", headers=auth_headers)
    imported = pick(client, auth_headers, {"name": "Amber Lagoon", "modes": "2v2"})

    assert listed.status_code == 502
    assert imported.status_code == 502
    # the status, and never the page the site refused with
    assert listed.json() == {"error": "fake.test answered 403"}
    assert [map["name"] for map in client.get("/maps").json()] == ["Concealed Hill"]


def test_a_list_stops_at_its_cap_by_name() -> None:
    rows = [SourceMap(name=f"Map {number:03}") for number in range(501, -1, -1)]

    found = matching(rows, "")

    assert len(found) == base.CATALOGUE_ROWS
    assert found[0].name == "Map 000"
    assert found[-1].name == "Map 499"


def test_every_source_reads_under_the_name_of_the_app() -> None:
    assert base._session.headers["User-Agent"] == base.USER_AGENT
    assert "github.com" in base.USER_AGENT


def test_liquipedia_lists_its_maps_past_each_continue(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A page's categories can split over two calls; it stays one row."""
    calls: list[dict[str, str]] = []
    answers = [
        {
            "continue": {"clcontinue": "1|Maps", "continue": "||"},
            "query": {
                "pages": [
                    {"title": "Twisted Meadows", "categories": [{"title": "X"}]},
                    {
                        "title": "Autumn Leaves",
                        "categories": [{"title": "Category:Maps (2 Players)"}],
                    },
                ]
            },
        },
        {
            "query": {
                "pages": [
                    {
                        "title": "Twisted Meadows",
                        "categories": [{"title": "Category:Maps (4 Players)"}],
                    },
                    {
                        "title": "Crown Lobby",
                        "categories": [{"title": "Category:Maps (12 Players)"}],
                    },
                    {"title": "Odd Page"},
                ]
            }
        },
    ]

    def fake_request(
        self: requests.Session,
        method: str,
        url: str,
        params: dict[str, str],
        **kwargs: object,
    ) -> FakeResponse:
        calls.append(params)
        return FakeResponse(answers[len(calls) - 1])

    monkeypatch.setattr(requests.Session, "request", fake_request)
    wiki = liquipedia.Liquipedia()

    rows = wiki.catalogue("")

    assert [(row.name, row.players, row.modes) for row in rows] == [
        ("Autumn Leaves", 2, "1v1"),
        ("Crown Lobby", 12, "ffa"),
        ("Odd Page", None, None),
        ("Twisted Meadows", 4, "2v2"),
    ]
    # the wiki refuses its files to a page on another site, so a list offers no picture
    assert {row.picture_url for row in rows} == {None}
    assert calls[1]["clcontinue"] == "1|Maps"
    assert calls[0]["format"] == "json"
    # the terms ask for a cache: a search reads what the process already holds
    assert [row.name for row in wiki.catalogue("autumn")] == ["Autumn Leaves"]
    assert len(calls) == 2


def test_liquipedia_finds_a_picture_through_the_infobox_by_lineage(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    pages = WIKI_PAGES | {"Plain Page": (2, "File:Plain_page.png")}

    def fake_request(
        self: requests.Session,
        method: str,
        url: str,
        params: dict[str, str],
        **kwargs: object,
    ) -> FakeResponse:
        if params.get("prop") == "revisions":
            # the wiki also holds a page with no picture in its infobox
            found = wiki_answer(params, pages)
            for page in found["query"]["pages"]:
                if page["title"] == "Turtle Rock":
                    page["revisions"][0]["slots"]["main"]["content"] = "|image=\n|x=1"
            return FakeResponse(found)
        return FakeResponse(wiki_answer(params, pages))

    monkeypatch.setattr(requests.Session, "request", fake_request)

    found = liquipedia.Liquipedia().find(
        ["Echo Isles v2", "Turtle Rock", "Plain Page", "Nonesuch"]
    )

    assert found["Echo Isles v2"].name == "Echo Isles"
    assert found["Echo Isles v2"].picture_url == f"{WIKI_FILES}Wc3EchoIsles.png"
    assert found["Echo Isles v2"].modes == "1v1"
    assert found["Echo Isles v2"].shortname is None
    # a file named with its prefix and underscores reads as the API titles it
    assert found["Plain Page"].picture_url == f"{WIKI_FILES}Plain page.png"
    assert found["Turtle Rock"].picture_url is None
    assert "Nonesuch" not in found


def test_liquipedia_does_not_walk_a_file_older_versions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A `continue` on one file's info only leads to its older versions, at two seconds each."""
    calls: list[dict[str, str]] = []

    def fake_request(
        self: requests.Session,
        method: str,
        url: str,
        params: dict[str, str],
        **kwargs: object,
    ) -> FakeResponse:
        calls.append(params)
        body = wiki_answer(params, WIKI_PAGES)
        if params.get("prop") == "imageinfo" and "iistart" not in params:
            body["continue"] = {"iistart": "2020-09-30T12:19:40Z", "continue": "||"}
        return FakeResponse(body)

    monkeypatch.setattr(requests.Session, "request", fake_request)

    found = liquipedia.Liquipedia().find(["Echo Isles"])

    assert found["Echo Isles"].picture_url == f"{WIKI_FILES}Wc3EchoIsles.png"
    assert [call.get("prop") for call in calls].count("imageinfo") == 1


@pytest.mark.parametrize(
    ("name", "page"),
    [
        ("Echo Isles", "Echo Isles"),
        ("Echo Isles v2", "Echo Isles 2"),
        # a version the wiki has no page of goes to the last one it has
        ("Echo Isles v3", "Echo Isles 2"),
    ],
)
def test_liquipedia_tells_two_pages_of_one_lineage_apart(
    monkeypatch: pytest.MonkeyPatch, name: str, page: str
) -> None:
    pages = {"Echo Isles": (2, "One.png"), "Echo Isles 2": (2, "Two.png")}
    monkeypatch.setattr(
        requests.Session,
        "request",
        lambda self, method, url, **kwargs: FakeResponse(
            wiki_answer(kwargs["params"], pages)
        ),
    )

    assert liquipedia.Liquipedia().find([name])[name].name == page


def test_liquipedia_keeps_its_calls_apart(monkeypatch: pytest.MonkeyPatch) -> None:
    waits: list[float] = []
    monkeypatch.setattr(liquipedia, "API_PAUSE", 2.0)
    monkeypatch.setattr(liquipedia, "_last_call", 0.0)
    monkeypatch.setattr(liquipedia, "sleep", waits.append)
    monkeypatch.setattr(
        requests.Session,
        "request",
        lambda self, method, url, **kwargs: FakeResponse({"query": {"pages": []}}),
    )

    liquipedia._call({})
    liquipedia._call({})

    assert len(waits) == 1
    assert 0 < waits[0] <= 2.0


def test_liquipedia_refusing_a_query_is_a_failure(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(
        requests.Session,
        "request",
        lambda self, method, url, **kwargs: FakeResponse({"error": {"code": "x"}}),
    )

    with pytest.raises(ExternalServiceError):
        liquipedia.Liquipedia().catalogue("")


def test_warcraft3_info_lists_its_maps_in_the_app_words(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    db = [
        {
            "name": "Echo Isles",
            "short": "EI",
            "tags": [{"mode": "1vs1"}, {"mode": "FFA"}, {"mode": "tower-defense"}],
            "image": {"file_name": "echo.webp"},
        },
        {"name": "Bare Map", "short": None, "tags": [], "image": None},
    ]
    monkeypatch.setattr(
        requests.Session,
        "request",
        lambda self, method, url, **kwargs: FakeResponse(db),
    )

    rows = map_sources.SOURCES["warcraft3_info"].catalogue("")

    assert [row.name for row in rows] == ["Bare Map", "Echo Isles"]
    assert (rows[1].modes, rows[1].shortname) == ("1v1,ffa", "EI")
    assert rows[1].picture_url and rows[1].picture_url.endswith("/echo.webp")
    assert (rows[0].modes, rows[0].shortname, rows[0].picture_url) == (None, None, None)
