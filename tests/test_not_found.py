"""A request that names a row which does not exist answers 404.

These routes answered 500 before, because the services signalled a
missing row with the exception the API maps to a server error. The status
is part of the contract the frontend and the Discord bot read, so it is
pinned here.
"""

from typing import Any

import pytest
from httpx2 import Client

MISSING = 999999

# (method, path, body) - every one names a row that does not exist.
ROUTES = [
    ("GET", "/maps/{id}", None),
    ("PUT", "/maps/{id}", {"name": "Nowhere"}),
    ("GET", "/matches/{id}", None),
    ("PUT", "/matches/{id}", {"playday": 1}),
    ("GET", "/seasons/{id}", None),
    ("PUT", "/seasons/{id}", {"name": "Nowhere"}),
    ("GET", "/teams/{id}", None),
    ("PUT", "/teams/{id}", {"name": "Nowhere"}),
    ("GET", "/teams/{id}/image", None),
    ("GET", "/series/{id}", None),
    # Both scores: the route checks the score before it looks the row up.
    ("PUT", "/series/{id}", {"player1_score": 2, "player2_score": 1}),
    ("GET", "/users/{id}", None),
    ("PUT", "/users/{id}", {"name": "Nowhere"}),
    ("GET", "/fantasy/teams/{id}", None),
    ("GET", "/fantasy/bets/{id}", None),
    ("GET", "/koth/events/{id}", None),
    ("PUT", "/koth/events/{id}", {"name": "Nowhere"}),
    ("GET", "/draft-series/{id}", None),
]


@pytest.mark.parametrize("method,path,body", ROUTES)
def test_missing_row_answers_404(
    client: Client,
    auth_headers: dict[str, str],
    seeded: dict[str, Any],
    method: str,
    path: str,
    body: dict[str, Any] | None,
) -> None:
    url = path.format(id=MISSING)
    resp = client.request(method, url, headers=auth_headers, json=body)
    assert resp.status_code == 404, resp.text


def test_the_body_carries_the_message_without_the_class_name(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    resp = client.get(f"/maps/{MISSING}", headers=auth_headers)
    assert resp.status_code == 404
    error = resp.json()["error"]
    assert "NotFound" not in error
    assert "not found" in error.lower()
