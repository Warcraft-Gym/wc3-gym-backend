"""PUT /user-info: a member edits their own profile, and only their own.

Signups being closed does not gate the edit; the battle tag is validated.
"""

from typing import Any

import pytest
from fastapi import FastAPI
from httpx2 import Client

from app.services.users import UserService
from tests.test_discord_auth import SESSION, stub_clerk


@pytest.fixture
def member(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """P1's Clerk session, with the W3C reads stubbed out."""
    monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
    monkeypatch.setattr(UserService, "validate_battle_tag", lambda self, tag: True)
    monkeypatch.setattr(UserService, "update_w3c_stats_by_id", lambda self, uid: None)
    stub_clerk(monkeypatch, account={"id": "1", "username": "p1", "avatar": None})
    return SESSION


def test_a_member_edits_their_own_profile(
    client: Client, seeded: dict[str, Any], member: dict[str, str], app: FastAPI
) -> None:
    resp = client.put(
        "/user-info",
        json={"country": "DE", "timezone": "Europe/Berlin"},
        headers=member,
    )
    assert resp.status_code == 200, resp.text
    user = resp.json()["user"]
    assert user["country"] == "DE"
    assert user["timezone"] == "Europe/Berlin"

    # the edit touched nothing else
    resp = client.get(f"/users/{user['id']}")
    assert resp.json()["battleTag"] == user["battleTag"]


def test_a_closed_signup_window_does_not_gate_the_edit(
    client: Client,
    seeded: dict[str, Any],
    member: dict[str, str],
    auth_headers: dict[str, str],
) -> None:
    resp = client.put(
        "/config/settings/signups_enabled",
        json={"value": "false"},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text

    resp = client.put("/user-info", json={"country": "SE"}, headers=member)
    assert resp.status_code == 200, resp.text


def test_a_bad_battle_tag_is_refused(
    client: Client,
    seeded: dict[str, Any],
    member: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(UserService, "validate_battle_tag", lambda self, tag: False)
    resp = client.put("/user-info", json={"battleTag": "No#0000"}, headers=member)
    assert resp.status_code == 400, resp.text


def test_an_empty_body_is_refused(
    client: Client, seeded: dict[str, Any], member: dict[str, str]
) -> None:
    resp = client.put("/user-info", json={}, headers=member)
    assert resp.status_code == 400, resp.text


def test_the_admin_token_is_not_a_member(
    client: Client, seeded: dict[str, Any], auth_headers: dict[str, str]
) -> None:
    resp = client.put("/user-info", json={"country": "DE"}, headers=auth_headers)
    assert resp.status_code == 401, resp.text
