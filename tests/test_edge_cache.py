"""The open reads the edge caches: each answers one copy for every caller."""

from typing import Any

import pytest

from app.services.w3c import W3CService
from tests.conftest import Client

LONG = "public, s-maxage=300, stale-while-revalidate=3600"
CAREER = "public, s-maxage=3600, stale-while-revalidate=3600"
LADDER = "public, s-maxage=900, stale-while-revalidate=3600"
SHORT = "public, s-maxage=120, stale-while-revalidate=600"

ROUTES = [
    ("/events", LONG),
    ("/leagues", LONG),
    ("/maps", LONG),
    ("/stats/career", CAREER),
    ("/config/w3c", LONG),
    ("/config/settings/score_system", LONG),
    ("/events/{season_id}/ladder/players", LADDER),
    ("/users/{player}/ladder", LADDER),
    ("/users/{player}/ladder?season_id={season_id}", LADDER),
    ("/users/{player}/history", SHORT),
    ("/leagues/{league_id}/teams", SHORT),
    ("/leagues/{league_id}/teams/basic", SHORT),
    ("/leagues/{league_id}/teams/{team_a_id}", SHORT),
]


@pytest.mark.parametrize(("path", "cache_control"), ROUTES)
def test_an_open_read_is_cacheable_at_the_edge(
    client: Client,
    seeded: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    path: str,
    cache_control: str,
) -> None:
    monkeypatch.setattr(W3CService, "current_season", lambda self: 20)
    url = path.format(player=seeded["player_ids"][0], **seeded)
    # no Origin and no token: the shape of a fill by curl or a bot
    resp = client.get(url)
    assert resp.status_code == 200, resp.text
    assert resp.headers["cache-control"] == cache_control
    assert resp.headers["access-control-allow-origin"] == "*"


FINISHED = "public, s-maxage=3600, stale-while-revalidate=86400"


@pytest.mark.parametrize(
    "path",
    [
        "/events/{season_id}/series",
        "/events/{season_id}/teams",
        "/events/{season_id}/teams/basic",
        "/events/{season_id}/teams/{team_a_id}",
    ],
)
def test_a_finished_event_is_cached_for_an_hour(
    client: Client, seeded: dict[str, Any], path: str
) -> None:
    from app.core.db import Session
    from app.models.season import Season
    from app.models.types import utcnow

    with Session.begin() as session:
        event = Season.get_by_id(session, seeded["season_id"])
        assert event is not None
        event.closed_at = utcnow()
    resp = client.get(path.format(**seeded))
    assert resp.status_code == 200, resp.text
    assert resp.headers["cache-control"] == FINISHED
    assert resp.headers["access-control-allow-origin"] == "*"


@pytest.mark.parametrize(
    "path", ["/events/{id}/series", "/events/{id}/teams", "/events/{id}/teams/basic"]
)
def test_an_event_not_finished_is_cached_for_two_minutes(
    client: Client, path: str
) -> None:
    from datetime import timedelta

    from app.models.types import utcnow
    from tests.test_events import add_event

    event_id = add_event(
        published=True, start_date=(utcnow() + timedelta(days=30)).date()
    )
    resp = client.get(path.format(id=event_id))
    assert resp.status_code == 200, resp.text
    assert resp.headers["cache-control"] == SHORT


def test_events_is_not_cached_for_an_admin(
    client: Client, auth_headers: dict[str, str]
) -> None:
    # an admin's bearer sees drafts, so the edge must never store this answer
    resp = client.get("/events", headers=auth_headers)
    assert resp.status_code == 200
    assert "public" not in resp.headers.get("cache-control", "")


def test_a_not_found_on_a_cached_route_is_not_cached(
    client: Client, seeded: dict[str, Any]
) -> None:
    resp = client.get(f"/events/{seeded['season_id']}/teams/999999")
    assert resp.status_code == 404
    assert "public" not in resp.headers.get("cache-control", "")


def test_a_w3c_outage_answer_is_not_cached(client: Client) -> None:
    # conftest refuses every third-party call, so w3champions reads as down
    resp = client.get("/config/w3c")
    assert resp.status_code == 200
    assert resp.json()["current_season"] is None
    assert "public" not in resp.headers.get("cache-control", "")
