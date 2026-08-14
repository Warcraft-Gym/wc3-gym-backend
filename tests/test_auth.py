"""Login and the JWT guard."""

from typing import Any

from httpx2 import Client


def test_login_with_admin_token(client: Client) -> None:
    resp = client.post("/login", json={"token": "test-admin-token"})
    assert resp.status_code == 200
    body = resp.json()
    assert "access_token" in body
    assert "refresh_token" in body


def test_login_with_bad_token(client: Client) -> None:
    resp = client.post("/login", json={"token": "wrong"})
    assert resp.status_code == 401


def test_guarded_route_without_token(client: Client) -> None:
    resp = client.get("/config/koth/nightbot-token")
    assert resp.status_code == 401


def test_guarded_route_with_token(
    client: Client, seeded: dict[str, Any], auth_headers: dict[str, str]
) -> None:
    resp = client.get("/config/koth/nightbot-token", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["token"] == "test-nightbot-token"


def test_refresh_rejects_access_token(
    client: Client, auth_headers: dict[str, str]
) -> None:
    # /refresh takes the refresh token, not the access token.
    resp = client.post("/refresh", headers=auth_headers)
    assert resp.status_code == 422
