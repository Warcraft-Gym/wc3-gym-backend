"""Every no-argument GET route answers with its expected status.

The route list matches the 20 rules in the URL map. The expected values
pin behavior on the seeded database, so a framework change that breaks
routing, auth, or serialization fails here first.
"""

import pytest

ROUTES = [
    ("/", 302),  # redirects to /apidocs/
    ("/apidocs/", 200),
    ("/apidocs/index.html", 302),
    ("/apispec.json", 200),
    ("/config/koth/nightbot-token", 401),  # jwt-guarded
    ("/config/settings", 200),
    ("/fantasy/bets", 200),
    ("/fantasy/teams", 200),
    ("/koth/events", 200),
    ("/koth/events/active", 200),
    ("/koth/signup", 401),  # needs the nightbot token parameter
    ("/maps", 200),
    ("/oauth2-redirect.html", 200),
    ("/player-series", 400),  # needs battleTag and token parameters
    ("/seasons", 200),
    ("/stats/career", 200),
    ("/teams", 200),
    ("/teams/basic", 200),
    ("/user-info", 400),  # needs battleTag and token parameters
    ("/users", 200),
]


@pytest.mark.parametrize("path,expected_status", ROUTES)
def test_get_status(client, seeded, path, expected_status):
    resp = client.get(path)
    assert resp.status_code == expected_status


@pytest.mark.parametrize("path", [p for p, s in ROUTES if s == 200 and "apidocs" not in p and p != "/oauth2-redirect.html"])
def test_get_returns_json(client, seeded, path):
    resp = client.get(path)
    assert resp.content_type.startswith("application/json")


def test_route_count(route_count):
    # 139 rules in the URL map, minus the static route the fixture excludes.
    assert route_count == 138
