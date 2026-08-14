"""Every no-argument GET route answers with its expected status.

The expected values pin behavior on the seeded database, so a change
that breaks routing, auth, or serialization fails here first.
"""

from typing import Any

import pytest
from httpx2 import Client

ROUTES = [
    ("/", 302),  # redirects to /docs
    ("/docs", 200),
    ("/openapi.json", 200),
    ("/config/koth/nightbot-token", 401),  # jwt-guarded
    ("/config/settings", 200),
    ("/fantasy/bets", 200),
    ("/fantasy/teams", 200),
    ("/koth/events", 200),
    ("/koth/events/active", 200),
    ("/koth/signup", 401),  # needs the nightbot token parameter
    ("/maps", 200),
    ("/player-series", 400),  # needs battleTag and token parameters
    ("/seasons", 200),
    ("/stats/career", 200),
    ("/teams", 200),
    ("/teams/basic", 200),
    ("/user-info", 400),  # needs battleTag and token parameters
    ("/users", 200),
]


@pytest.mark.parametrize("path,expected_status", ROUTES)
def test_get_status(
    client: Client, seeded: dict[str, Any], path: str, expected_status: int
) -> None:
    resp = client.get(path)
    assert resp.status_code == expected_status


@pytest.mark.parametrize(
    "path",
    [p for p, s in ROUTES if s == 200 and p != "/docs"],
)
def test_get_returns_json(client: Client, seeded: dict[str, Any], path: str) -> None:
    resp = client.get(path)
    assert resp.headers["content-type"].startswith("application/json")
