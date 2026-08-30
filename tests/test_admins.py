"""The admins the app names: the grants, the environment bootstrap, and /me.

The routes are the Config page's; the caller of a self-revoke is a Clerk
session, because the token login is nobody's grant.
"""

from typing import Any

import pytest
from httpx2 import Client

from app.core.db import Session
from app.models.relationships import DBUserSeasonSignup
from tests.test_discord_auth import ACCOUNT, SESSION, stub_clerk

ENV_ID = "220202568490418179"


def test_an_admin_is_added_listed_and_deleted(
    client: Client, monkeypatch: pytest.MonkeyPatch, auth_headers: dict[str, str]
) -> None:
    monkeypatch.setenv("ADMIN_DISCORD_IDS", ENV_ID)
    created = client.post(
        "/config/admins",
        json={"discord_id": "42", "name": "Player"},
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    assert created.json()["granted_by"] == "admin"
    assert created.json()["source"] == "app"

    listed = client.get("/config/admins", headers=auth_headers).json()
    # The environment ids come first, then the grants in the order they were made
    assert [(one["discord_id"], one["source"]) for one in listed] == [
        (ENV_ID, "env"),
        ("42", "app"),
    ]

    assert client.delete("/config/admins/42", headers=auth_headers).status_code == 204
    assert client.get("/config/admins", headers=auth_headers).json() == [listed[0]]


def test_an_admin_cannot_revoke_itself(
    client: Client, monkeypatch: pytest.MonkeyPatch, auth_headers: dict[str, str]
) -> None:
    resp = client.post(
        "/config/admins", json={"discord_id": ACCOUNT["id"]}, headers=auth_headers
    )
    assert resp.status_code == 201, resp.text
    stub_clerk(monkeypatch)

    resp = client.delete(f"/config/admins/{ACCOUNT['id']}", headers=SESSION)

    assert resp.status_code == 400
    assert resp.json() == {"error": "Admins cannot revoke themselves"}


def test_an_environment_admin_is_neither_granted_nor_revoked(
    client: Client, monkeypatch: pytest.MonkeyPatch, auth_headers: dict[str, str]
) -> None:
    monkeypatch.setenv("ADMIN_DISCORD_IDS", ENV_ID)
    added = client.post(
        "/config/admins", json={"discord_id": ENV_ID}, headers=auth_headers
    )
    assert added.status_code == 400
    assert added.json() == {"error": "Already an admin by environment"}
    gone = client.delete(f"/config/admins/{ENV_ID}", headers=auth_headers)
    assert gone.status_code == 400
    assert gone.json() == {"error": "Already an admin by environment"}


def test_an_unknown_admin_answers_404(
    client: Client, auth_headers: dict[str, str]
) -> None:
    resp = client.delete("/config/admins/404", headers=auth_headers)
    assert resp.status_code == 404
    assert resp.json() == {"error": "Admin not found by Discord id: 404"}


def test_me_names_the_token_login_a_superadmin(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    body = client.get("/me", headers=auth_headers).json()

    assert body["superadmin"] is True
    assert body["name"] == "Super Admin"
    assert body["season_id"] == seeded["season_id"]
    # The token login has no users row, so it signed up for nothing
    assert body["signed_up"] is False


def test_me_says_whether_the_player_signed_up(
    client: Client, monkeypatch: pytest.MonkeyPatch, seeded: dict[str, Any]
) -> None:
    stub_clerk(monkeypatch, account={**ACCOUNT, "id": "1"})
    assert client.get("/me", headers=SESSION).json()["signed_up"] is False

    with Session() as session:
        session.add(
            DBUserSeasonSignup(
                user_id=seeded["player_ids"][0], season_id=seeded["season_id"]
            )
        )
        session.commit()

    body = client.get("/me", headers=SESSION).json()
    assert body["signed_up"] is True
    assert body["superadmin"] is False
    assert body["season_id"] == seeded["season_id"]
