"""The open reads the edge caches: each answers one copy for every caller."""

from typing import Any

import pytest

from tests.conftest import Client

LONG = "public, s-maxage=300, stale-while-revalidate=3600"
LADDER = "public, s-maxage=900, stale-while-revalidate=3600"
SHORT = "public, s-maxage=120, stale-while-revalidate=600"

ROUTES = [
    ("/leagues", LONG),
    ("/maps", LONG),
    ("/config/w3c", LONG),
    ("/config/settings/score_system", LONG),
    ("/events/{season_id}/ladder/players", LADDER),
    ("/users/{player}/ladder", LADDER),
    ("/users/{player}/ladder?season_id={season_id}", LADDER),
    ("/users/{player}/history", SHORT),
    ("/events/{season_id}/teams", SHORT),
    ("/events/{season_id}/teams/basic", SHORT),
    ("/events/{season_id}/teams/{team_a_id}", SHORT),
    ("/leagues/{league_id}/teams", SHORT),
    ("/leagues/{league_id}/teams/basic", SHORT),
    ("/leagues/{league_id}/teams/{team_a_id}", SHORT),
]


@pytest.mark.parametrize(("path", "cache_control"), ROUTES)
def test_an_open_read_is_cacheable_at_the_edge(
    client: Client, seeded: dict[str, Any], path: str, cache_control: str
) -> None:
    url = path.format(player=seeded["player_ids"][0], **seeded)
    # no Origin and no token: the shape of a fill by curl or a bot
    resp = client.get(url)
    assert resp.status_code == 200, resp.text
    assert resp.headers["cache-control"] == cache_control
    assert resp.headers["access-control-allow-origin"] == "*"


def test_a_not_found_on_a_cached_route_is_not_cached(
    client: Client, seeded: dict[str, Any]
) -> None:
    resp = client.get(f"/events/{seeded['season_id']}/teams/999999")
    assert resp.status_code == 404
    assert "public" not in resp.headers.get("cache-control", "")
