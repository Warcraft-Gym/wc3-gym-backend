"""Login and the JWT guard."""

from typing import Any

from httpx2 import Client

# A 1x1 PNG. The route stores the bytes as they arrive.
PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01"
    b"\x08\x06\x00\x00\x00\x1f\x15\xc4\x89\x00\x00\x00\nIDATx\x9cc\x00\x01"
    b"\x00\x00\x05\x00\x01\r\n-\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)


def test_login_with_admin_token(client: Client) -> None:
    resp = client.post("/login", json={"token": "test-admin-token"})
    assert resp.status_code == 200
    body = resp.json()
    assert "access_token" in body
    assert "refresh_token" in body


def test_login_with_bad_token(client: Client) -> None:
    resp = client.post("/login", json={"token": "wrong"})
    assert resp.status_code == 401
    assert resp.json() == {"error": "Bad admin token"}


def test_login_without_a_token_field(client: Client) -> None:
    resp = client.post("/login", json={"admin_token": "test-admin-token"})
    assert resp.status_code == 422
    assert "error" in resp.json()


def test_login_with_an_empty_body(client: Client) -> None:
    resp = client.post("/login", json={})
    assert resp.status_code == 422
    assert "error" in resp.json()


def test_guarded_route_without_token(client: Client) -> None:
    resp = client.get("/config/koth/nightbot-token")
    assert resp.status_code == 401
    assert resp.json() == {"error": "Missing Authorization Header"}


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


def test_team_w3c_sync_needs_a_token(client: Client, seeded: dict[str, Any]) -> None:
    resp = client.post(
        f"/teams/w3c_sync/{seeded['team_a_id']}/seasons/{seeded['season_id']}"
    )
    assert resp.status_code == 401


def test_season_w3c_sync_needs_a_token(client: Client, seeded: dict[str, Any]) -> None:
    resp = client.post(f"/seasons/{seeded['season_id']}/w3c_sync")
    assert resp.status_code == 401


def test_fantasy_team_import_needs_a_token(
    client: Client, seeded: dict[str, Any]
) -> None:
    resp = client.post(
        "/fantasy/import/teams",
        params={"season_id": str(seeded["season_id"])},
        files={"file": ("teams.xlsx", b"", "application/vnd.ms-excel")},
    )
    assert resp.status_code == 401


def test_fantasy_bet_import_needs_a_token(
    client: Client, seeded: dict[str, Any]
) -> None:
    resp = client.post(
        "/fantasy/import/bets",
        params={"season_id": str(seeded["season_id"])},
        files={"file": ("bets.xlsx", b"", "application/vnd.ms-excel")},
    )
    assert resp.status_code == 401


def test_team_image_upload_needs_a_token(
    client: Client, seeded: dict[str, Any]
) -> None:
    resp = client.post(
        f"/teams/{seeded['team_a_id']}/image",
        files={"image": ("icon.png", PNG, "image/png")},
    )
    assert resp.status_code == 401


def test_team_image_upload_works_with_a_token(
    client: Client, seeded: dict[str, Any], auth_headers: dict[str, str]
) -> None:
    team_id = seeded["team_a_id"]
    resp = client.post(
        f"/teams/{team_id}/image",
        files={"image": ("icon.png", PNG, "image/png")},
        headers=auth_headers,
    )
    assert resp.status_code == 200

    stored = client.get(f"/teams/{team_id}/image")
    assert stored.status_code == 200
    assert stored.content == PNG


def test_team_image_download_stays_public(
    client: Client, seeded: dict[str, Any]
) -> None:
    # The public site pulls team icons without a token. The seeded team has
    # no icon, so a reachable route answers 404 rather than 401.
    resp = client.get(f"/teams/{seeded['team_a_id']}/image")
    assert resp.status_code == 404
