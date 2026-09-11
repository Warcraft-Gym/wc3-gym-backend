"""PUT /user-info: a member edits their own profile, and only their own.

The battle tag is validated.
"""

from typing import Any
from urllib.parse import quote

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


def test_a_user_reads_by_battle_tag_as_well_as_by_id(
    client: Client, seeded: dict[str, Any]
) -> None:
    """The battle tag is the URL key; the id keeps working for old links."""
    by_id = client.get("/users/1").json()
    tag = by_id["battleTag"]
    assert "#" in tag
    by_tag = client.get(f"/users/{quote(tag, safe='')}").json()
    assert by_tag["id"] == by_id["id"]
    # the lookup ignores case, like the unique index
    assert client.get(f"/users/{quote(tag.upper(), safe='')}").json()["id"] == 1
    # a key that is neither a known id nor a tag
    assert client.get("/users/nobody%230000").status_code == 404
    assert client.get("/users/1%230000").status_code == 404
