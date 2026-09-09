"""The player routes identify the member by their Clerk session.

The session names the Discord account; the profile form and the dashboard
never carry the identity themselves.
"""

from typing import Any

import pytest
from fastapi import FastAPI
from httpx2 import Client

from tests.test_discord_auth import SESSION, stub_clerk


@pytest.fixture
def w3c_free(monkeypatch: pytest.MonkeyPatch, app: FastAPI) -> None:
    """Signup calls W3Champions twice. Answer both without the network."""
    from app.services.users import UserService

    monkeypatch.setattr(UserService, "validate_battle_tag", lambda self, tag: True)
    monkeypatch.setattr(
        UserService, "update_w3c_stats_by_id", lambda self, user_id: None
    )


SIGNUP_BODY = {"name": "P9", "battleTag": "P9#1234", "race": "HU", "country": "DE"}


def member_session(
    monkeypatch: pytest.MonkeyPatch,
    discord_id: str = "1",
    name: str = "p1",
    a_member: bool = True,
) -> dict[str, str]:
    """Stand Clerk and Discord in for one account, and answer the headers it sends."""
    stub_clerk(
        monkeypatch,
        a_member=a_member,
        account={"id": discord_id, "username": name, "avatar": None},
    )
    return SESSION


@pytest.fixture
def member_headers(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    return member_session(monkeypatch)


def test_signup_takes_the_discord_fields_from_the_session(
    client: Client, w3c_free: None, member_headers: dict[str, str]
) -> None:
    """The session wins over the body."""
    resp = client.post(
        "/signup", json=SIGNUP_BODY | {"discordId": "999"}, headers=member_headers
    )

    assert resp.status_code == 201, resp.text
    assert resp.json()["discordId"] == "1"
    assert resp.json()["discordTag"] == "p1"


def test_player_series_on_a_session_reads_the_current_season(
    client: Client, seeded: dict[str, Any], member_headers: dict[str, str]
) -> None:
    """A signed-in player has no token to carry the season, so the pinned one is used.

    A newer season is stored and the setting names the older one. Without it the
    fallback to the highest season id would answer the newer season, which
    carries no rounds.
    """
    from app.core.db import Session
    from app.models.season import Season
    from app.models.settings import Settings

    with Session() as session:
        session.add(Season(name="Later Season", series_per_round=2))
        session.add(Settings(key="current_gnl_season", value=str(seeded["season_id"])))
        session.commit()

    body = client.get("/player-series", headers=member_headers).json()

    assert body["season_id"] == seeded["season_id"]
    assert body["round_count"] == 4
    assert body["availability"] == []


def test_player_series_answers_404_for_a_member_without_a_row(
    client: Client, seeded: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    headers = member_session(monkeypatch, "no-such-id")

    resp = client.get("/player-series", headers=headers)

    assert resp.status_code == 404, resp.text
    assert resp.json() == {"error": "player_not_found"}


def test_an_admin_token_carries_no_discord_id(
    client: Client, seeded: dict[str, Any], auth_headers: dict[str, str]
) -> None:
    """The bot's admin token logs in as no player, so a player route turns it away."""
    resp = client.get("/player-series", headers=auth_headers)

    assert resp.status_code == 401, resp.text
    assert resp.json() == {"error": "not_a_discord_member"}


def test_a_guest_reads_no_player_route(
    client: Client, seeded: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """An account outside the guild logs in, and the player routes turn it away."""
    headers = member_session(monkeypatch, a_member=False)

    resp = client.get("/player-series", headers=headers)

    assert resp.status_code == 403, resp.text
    assert resp.json() == {"error": "No valid WC3 Gym server membership found for user"}


def test_signup_stores_the_time_zone(
    client: Client, w3c_free: None, member_headers: dict[str, str]
) -> None:
    """The profile form sends the browser's IANA name."""
    resp = client.post(
        "/signup",
        json=SIGNUP_BODY | {"timezone": "America/New_York"},
        headers=member_headers,
    )

    assert resp.status_code == 201, resp.text
    assert resp.json()["timezone"] == "America/New_York"


def test_signup_refuses_an_unknown_time_zone(
    client: Client, w3c_free: None, member_headers: dict[str, str]
) -> None:
    resp = client.post(
        "/signup",
        json=SIGNUP_BODY | {"timezone": "Mars/Olympus"},
        headers=member_headers,
    )

    assert resp.status_code == 422, resp.text
    assert "Mars/Olympus" in resp.json()["error"]
    assert client.get("/users").json() == []
