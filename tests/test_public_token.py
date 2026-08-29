"""The one-time token store, under parallel requests.

The store is a plain dict that the public routes share. The application
answers requests in parallel, so the
cleanup must tolerate a token that another request removes, and the
signup route must let only one of two parallel requests create the user.

The player routes also take a Clerk session, which is the identity path
the store gives way to; the last tests cover it.
"""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from httpx2 import Client

from tests.test_discord_auth import SESSION, stub_clerk


@pytest.fixture(autouse=True)
def empty_store() -> Iterator[dict[str, dict[str, Any]]]:
    """The store is process-global, so empty it around each test."""
    from app.api.routes.public import _token_store

    _token_store.clear()
    yield _token_store
    _token_store.clear()


def entry(access_type: str = "signup", minutes: int = 5) -> dict[str, Any]:
    return {
        "discord_id": "1",
        "discord_tag": "p1",
        "season_id": None,
        "access_type": access_type,
        "expires_at": datetime.now(UTC) + timedelta(minutes=minutes),
    }


class DroppingEntry(dict):
    """An entry that removes another token when the cleanup reads its expiry.

    This is the parallel delete, at the one moment that breaks the cleanup:
    inside the walk over the store.
    """

    def __init__(
        self, store: dict[str, Any], victim: str, fields: dict[str, Any]
    ) -> None:
        super().__init__(fields)
        self._store = store
        self._victim = victim

    def __getitem__(self, key: str) -> Any:  # noqa: ANN401  # a stored value
        if key == "expires_at":
            dict.pop(self._store, self._victim, None)
        return super().__getitem__(key)


def test_cleanup_tolerates_a_token_removed_during_the_walk(
    empty_store: dict[str, dict[str, Any]],
) -> None:
    """HARD GATE: the walk takes a snapshot and the delete tolerates a gap."""
    from app.api.routes.public import _cleanup_expired

    empty_store["first"] = DroppingEntry(empty_store, "second", entry(minutes=-5))
    empty_store["second"] = entry(minutes=-5)
    empty_store["live"] = entry()

    _cleanup_expired()

    assert set(empty_store) == {"live"}


def test_cleanup_drops_only_the_expired_tokens(
    empty_store: dict[str, dict[str, Any]],
) -> None:
    from app.api.routes.public import _cleanup_expired

    empty_store["old"] = entry(minutes=-1)
    empty_store["new"] = entry()

    _cleanup_expired()

    assert set(empty_store) == {"new"}


def test_delete_answers_not_found_the_second_time(
    client: Client, empty_store: dict[str, dict[str, Any]]
) -> None:
    """Two parallel deletes: one deletes the token, the other gets a 404."""
    empty_store["t"] = entry()

    assert client.delete("/public-token/t").status_code == 200
    assert client.delete("/public-token/t").status_code == 404


@pytest.fixture
def w3c_free(monkeypatch: pytest.MonkeyPatch, app: FastAPI) -> None:
    """Signup calls W3Champions twice. Answer both without the network."""
    from app.services.users import UserService

    monkeypatch.setattr(UserService, "validate_battle_tag", lambda self, tag: True)
    monkeypatch.setattr(
        UserService, "update_w3c_stats_by_id", lambda self, user_id: None
    )


SIGNUP_BODY = {"name": "P9", "battleTag": "P9#1234", "race": "HU", "country": "DE"}


def test_signup_spends_the_token(
    client: Client, empty_store: dict[str, dict[str, Any]], w3c_free: None
) -> None:
    """HARD GATE: the token pays for one user, so the second post gets a 404."""
    empty_store["t"] = entry()

    first = client.post("/signup", json={"token": "t"} | SIGNUP_BODY)
    assert first.status_code == 201
    assert "t" not in empty_store

    second = client.post("/signup", json={"token": "t"} | SIGNUP_BODY)
    assert second.status_code == 404
    assert second.json()["error"] == "token_not_found_or_expired"


def test_signup_stops_when_a_parallel_request_takes_the_token(
    client: Client,
    empty_store: dict[str, dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
    app: FastAPI,
) -> None:
    """HARD GATE: the other request takes the token during the W3C check.

    The BattleTag check goes over the network, so it is the long window in
    which a second post can take the same token. Only one user is made.
    """
    from app.services.users import UserService

    def take_the_token(self: UserService, battle_tag: str) -> bool:
        empty_store.pop("t", None)
        return True

    monkeypatch.setattr(UserService, "validate_battle_tag", take_the_token)
    monkeypatch.setattr(
        UserService, "update_w3c_stats_by_id", lambda self, user_id: None
    )
    empty_store["t"] = entry()

    resp = client.post("/signup", json={"token": "t"} | SIGNUP_BODY)

    assert resp.status_code == 404
    assert resp.json()["error"] == "token_not_found_or_expired"
    assert client.get("/users").json() == []


def test_signup_keeps_the_token_after_a_bad_battle_tag(
    client: Client,
    empty_store: dict[str, dict[str, Any]],
    monkeypatch: pytest.MonkeyPatch,
    app: FastAPI,
) -> None:
    """The signup page shows the error and the player posts the form again."""
    from app.services.users import UserService

    monkeypatch.setattr(UserService, "validate_battle_tag", lambda self, tag: False)
    empty_store["t"] = entry()

    resp = client.post("/signup", json={"token": "t"} | SIGNUP_BODY)

    assert resp.status_code == 400
    assert "t" in empty_store


def test_signup_keeps_the_token_after_a_missing_field(
    client: Client, empty_store: dict[str, dict[str, Any]], w3c_free: None
) -> None:
    empty_store["t"] = entry()

    resp = client.post("/signup", json={"token": "t", "name": "P9"})

    assert resp.status_code == 400
    assert "t" in empty_store


def test_signup_keeps_the_token_of_another_access_type(
    client: Client, empty_store: dict[str, dict[str, Any]], w3c_free: None
) -> None:
    empty_store["t"] = entry(access_type="dashboard")

    resp = client.post("/signup", json={"token": "t"} | SIGNUP_BODY)

    assert resp.status_code == 400
    assert resp.json()["error"] == "invalid_token_type"
    assert "t" in empty_store


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
    """The session wins over the body, the same way the token entry does."""
    resp = client.post(
        "/signup", json=SIGNUP_BODY | {"discordId": "999"}, headers=member_headers
    )

    assert resp.status_code == 201, resp.text
    assert resp.json()["discordId"] == "1"
    assert resp.json()["discordTag"] == "p1"


def test_player_series_answers_the_linked_players_series(
    client: Client, seeded: dict[str, Any], member_headers: dict[str, str]
) -> None:
    resp = client.get("/player-series", headers=member_headers)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["player"]["discordId"] == "1"
    assert body["discord_id"] == "1"
    assert len(body["series"]) == int(resp.headers["X-Total-Count"])


def test_player_series_answers_404_for_a_member_without_a_row(
    client: Client, seeded: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    headers = member_session(monkeypatch, "no-such-id")

    resp = client.get("/player-series", headers=headers)

    assert resp.status_code == 404, resp.text
    assert resp.json() == {"error": "player_not_found"}


def test_a_bet_of_another_player_answers_403_on_the_session_path(
    client: Client, seeded: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The seeded bet belongs to P1, and the session names P2."""
    bet_id = client.get("/fantasy/bets").json()[0]["id"]
    headers = member_session(monkeypatch, "2", "p2")

    resp = client.put(f"/fantasy-bet/{bet_id}", json={}, headers=headers)

    assert resp.status_code == 403, resp.text
    assert resp.json() == {
        "error": "unauthorized",
        "message": "You can only update your own bets",
    }


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


def test_the_admin_user_routes_take_the_time_zone(
    client: Client, w3c_free: None, auth_headers: dict[str, str]
) -> None:
    """The same field on the admin form, validated by the request model."""
    user = client.post(
        "/users",
        json=SIGNUP_BODY
        | {"discordTag": "p9", "discordId": "9", "timezone": "Europe/Berlin"},
        headers=auth_headers,
    )
    assert user.status_code == 201, user.text
    assert user.json()["timezone"] == "Europe/Berlin"

    bad = client.put(
        f"/users/{user.json()['id']}",
        json={"timezone": "Mars/Olympus"},
        headers=auth_headers,
    )
    assert bad.status_code == 422, bad.text
    assert "Mars/Olympus" in bad.json()["error"]
