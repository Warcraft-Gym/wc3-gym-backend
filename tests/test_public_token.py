"""The one-time token store, under parallel requests.

The store is a plain dict that the public routes share. The application
answers requests in parallel, so the
cleanup must tolerate a token that another request removes, and the
signup route must let only one of two parallel requests create the user.
"""

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from httpx2 import Client


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
    monkeypatch.setattr(UserService, "update_w3c_stats_by_id", lambda self, user_id: None)


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
    monkeypatch.setattr(UserService, "update_w3c_stats_by_id", lambda self, user_id: None)
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
