"""Login and the JWT guard."""


def test_login_with_admin_token(client):
    resp = client.post("/login", json={"token": "test-admin-token"})
    assert resp.status_code == 200
    body = resp.get_json()
    assert "access_token" in body
    assert "refresh_token" in body


def test_login_with_bad_token(client):
    resp = client.post("/login", json={"token": "wrong"})
    assert resp.status_code == 401


def test_guarded_route_without_token(client):
    resp = client.get("/config/koth/nightbot-token")
    assert resp.status_code == 401


def test_guarded_route_with_token(client, seeded, auth_headers):
    resp = client.get("/config/koth/nightbot-token", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.get_json()["token"] == "test-nightbot-token"


def test_refresh_rejects_access_token(client, auth_headers):
    # /refresh takes the refresh token, not the access token.
    resp = client.post("/refresh", headers=auth_headers)
    assert resp.status_code == 422
