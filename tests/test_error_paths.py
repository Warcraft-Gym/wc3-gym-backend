"""The status and the body a failing request answers, path by path.

The public pages, the admin frontend and the Discord bot branch on the
error string, so a renamed message or a changed status changes what a
consumer shows. Every assertion below names the exact body the code
answers today, so a refactor of where errors are raised has to keep it.
"""

import importlib
import inspect
import logging
import pkgutil
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any, Never

import pytest
from fastapi import FastAPI
from httpx2 import Client, Response

from app.api import routes
from app.core.exceptions import ExternalServiceError, W3CThrottledError
from app.services import w3c
from app.services.maps import MapService
from app.services.users import UserService
from app.services.w3c import W3CService

BOT_TOKEN = "test-bot-client-token"


@pytest.fixture(autouse=True)
def empty_store() -> Iterator[dict[str, dict[str, Any]]]:
    """The store is process-global, so empty it around each test."""
    from app.api.routes.public import _token_store

    _token_store.clear()
    yield _token_store
    _token_store.clear()


def mint(
    store: dict[str, dict[str, Any]],
    access_type: str = "fantasy",
    discord_id: str = "1",
    minutes: int = 5,
) -> str:
    token = f"token-{access_type}-{discord_id}"
    store[token] = {
        "discord_id": discord_id,
        "discord_tag": f"p{discord_id}",
        "season_id": None,
        "access_type": access_type,
        "expires_at": datetime.now(UTC) + timedelta(minutes=minutes),
    }
    return token


def call(client: Client, method: str, path: str, token: str | None = None) -> Response:
    """A token rides in the query on GET and DELETE, in the body elsewhere."""
    if method in ("GET", "DELETE"):
        return client.request(method, path, params={"token": token} if token else None)
    return client.request(method, path, json={"token": token} if token else {})


# Every public route that spends a one-time token.
TOKEN_ROUTES = [
    ("POST", "/signup"),
    ("GET", "/player-series"),
    ("PUT", "/player-series/1"),
    ("GET", "/user-info"),
    ("POST", "/fantasy-team"),
    ("POST", "/fantasy-bet"),
    ("PUT", "/fantasy-bet/1"),
    ("DELETE", "/fantasy-bet/1"),
]

# The three bet routes look the player up before they touch the bet.
BET_ROUTES = [
    ("POST", "/fantasy-bet"),
    ("PUT", "/fantasy-bet/1"),
    ("DELETE", "/fantasy-bet/1"),
]


@pytest.mark.parametrize("method,path", TOKEN_ROUTES)
def test_a_request_without_a_token_answers_400(
    client: Client, method: str, path: str
) -> None:
    resp = call(client, method, path)
    assert resp.status_code == 400, resp.text
    assert resp.json() == {"error": "missing token"}


@pytest.mark.parametrize("method,path", TOKEN_ROUTES)
def test_an_unknown_token_answers_404(client: Client, method: str, path: str) -> None:
    resp = call(client, method, path, token="no-such-token")
    assert resp.status_code == 404, resp.text
    assert resp.json() == {"error": "token_not_found_or_expired"}


@pytest.mark.parametrize("method,path", TOKEN_ROUTES)
def test_an_expired_token_answers_404(
    client: Client,
    empty_store: dict[str, dict[str, Any]],
    method: str,
    path: str,
) -> None:
    token = mint(empty_store, minutes=-1)

    resp = call(client, method, path, token=token)

    assert resp.status_code == 404, resp.text
    assert resp.json() == {"error": "token_not_found_or_expired"}
    assert token not in empty_store


@pytest.mark.parametrize("method,path", BET_ROUTES)
def test_a_bet_for_an_unknown_player_answers_404(
    client: Client,
    empty_store: dict[str, dict[str, Any]],
    seeded: dict[str, Any],
    method: str,
    path: str,
) -> None:
    token = mint(empty_store, discord_id="no-such-discord-id")

    resp = call(client, method, path, token=token)

    assert resp.status_code == 404, resp.text
    assert resp.json()["error"] == "user_not_found"


def test_the_dashboard_of_an_unknown_player_answers_404(
    client: Client, empty_store: dict[str, dict[str, Any]], seeded: dict[str, Any]
) -> None:
    """The dashboard says player_not_found where the bet routes say user_not_found."""
    token = mint(empty_store, access_type="dashboard", discord_id="no-such-discord-id")

    resp = client.get("/player-series", params={"token": token})

    assert resp.status_code == 404, resp.text
    assert resp.json() == {"error": "player_not_found"}


@pytest.mark.parametrize(
    "method,message",
    [
        ("PUT", "You can only update your own bets"),
        ("DELETE", "You can only delete your own bets"),
    ],
)
def test_a_bet_of_another_player_answers_403(
    client: Client,
    empty_store: dict[str, dict[str, Any]],
    seeded: dict[str, Any],
    method: str,
    message: str,
) -> None:
    """The seeded bet belongs to P1, and the token names P2."""
    bet_id = client.get("/fantasy/bets").json()[0]["id"]
    token = mint(empty_store, discord_id="2")

    resp = call(client, method, f"/fantasy-bet/{bet_id}", token=token)

    assert resp.status_code == 403, resp.text
    assert resp.json() == {"error": "unauthorized", "message": message}


def test_fantasy_team_creation_answers_the_closed_string(
    client: Client, empty_store: dict[str, dict[str, Any]], app: FastAPI
) -> None:
    """The registration page branches on this string, not on the status."""
    from app.core.db import Session
    from app.models.settings import Settings

    with Session() as session:
        session.add(Settings(key="fantasy_team_creation_enabled", value="false"))
        session.commit()
    token = mint(empty_store)

    resp = client.post("/fantasy-team", json={"token": token})

    assert resp.status_code == 403, resp.text
    assert resp.json()["error"] == "fantasy_team_creation_closed"


def test_the_access_helper_refuses_a_wrong_client_token(
    client: Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BOT_CLIENT_TOKEN", BOT_TOKEN)

    resp = client.post("/public-access-helper", json={"client_token": "wrong"})

    assert resp.status_code == 401
    assert resp.json() == {"error": "unauthorized"}


def test_the_access_helper_refuses_a_missing_discord_id(
    client: Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BOT_CLIENT_TOKEN", BOT_TOKEN)

    resp = client.post(
        "/public-access-helper",
        json={"client_token": BOT_TOKEN, "access_type": "signup"},
    )

    assert resp.status_code == 400
    assert resp.json() == {"error": "missing parameters"}


def test_the_access_helper_refuses_an_unknown_access_type(
    client: Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("BOT_CLIENT_TOKEN", BOT_TOKEN)

    resp = client.post(
        "/public-access-helper",
        json={
            "client_token": BOT_TOKEN,
            "discord_id": "1",
            "discord_tag": "p1",
            "access_type": "admin",
        },
    )

    assert resp.status_code == 400
    assert resp.json() == {"error": "invalid access_type"}


def refuse_w3c(monkeypatch: pytest.MonkeyPatch, failure: Exception) -> None:
    def raise_it(
        self: W3CService, method: str, url: str, params: dict[str, Any] | None = None
    ) -> Never:
        raise failure

    monkeypatch.setattr(W3CService, "send_request", raise_it)


@pytest.mark.parametrize(
    "failure",
    [ExternalServiceError("boom"), W3CThrottledError("slow down")],
    ids=["external_service", "throttled"],
)
def test_a_w3c_failure_answers_502_with_its_message(
    client: Client,
    auth_headers: dict[str, str],
    seeded: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    failure: Exception,
) -> None:
    refuse_w3c(monkeypatch, failure)
    user_id = seeded["player_ids"][0]

    resp = client.post(f"/users/w3c_sync/{user_id}", headers=auth_headers)

    assert resp.status_code == 502, resp.text
    assert resp.json() == {"error": str(failure)}


def test_a_plain_w3c_failure_answers_502_with_its_message(
    client: Client,
    auth_headers: dict[str, str],
    seeded: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """w3champions answers 200 with a body that is not JSON."""

    class NotJson:
        status_code = 200
        headers: dict[str, str] = {}
        text = "plain text"

        def json(self) -> Never:
            raise ValueError("no JSON here")

    class Session:
        def request(self, *args: object, **kwargs: object) -> NotJson:
            return NotJson()

    monkeypatch.setattr(w3c, "_session", Session())
    user_id = seeded["player_ids"][0]

    resp = client.post(f"/users/w3c_sync/{user_id}", headers=auth_headers)

    assert resp.status_code == 502, resp.text
    assert resp.json() == {"error": "plain text"}


def test_a_query_on_an_unknown_column_answers_400(client: Client) -> None:
    """The route checks that the query parses, not that it names a column."""
    resp = client.post("/maps/search", params={"query": "nosuchcolumn == 1"})

    assert resp.status_code == 400, resp.text
    assert resp.json() == {"error": "No search criteria was defined!"}


def errors(caplog: pytest.LogCaptureFixture) -> list[logging.LogRecord]:
    return [record for record in caplog.records if record.levelno >= logging.ERROR]


def test_a_missing_row_writes_no_error_record(
    client: Client, caplog: pytest.LogCaptureFixture
) -> None:
    """A caller who asks for a row that is gone is not an incident."""
    with caplog.at_level(logging.ERROR):
        resp = client.get("/maps/999999")

    assert resp.status_code == 404
    assert errors(caplog) == []


def test_a_bug_writes_one_error_record_with_the_traceback(
    client: Client, caplog: pytest.LogCaptureFixture, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The body names no detail, so the log is the only place to read it."""

    def broken(self: MapService, **kwargs: object) -> Never:
        raise RuntimeError("an internal detail the client must not see")

    monkeypatch.setattr(MapService, "getAll", broken)

    with caplog.at_level(logging.ERROR):
        resp = client.get("/maps")

    assert resp.status_code == 500
    assert len(errors(caplog)) == 1
    assert errors(caplog)[0].exc_info


def test_a_failed_player_lookup_logs_the_traceback(
    client: Client,
    empty_store: dict[str, dict[str, Any]],
    caplog: pytest.LogCaptureFixture,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def broken(self: UserService, discord_id: str) -> Never:
        raise RuntimeError("the lookup fell over")

    monkeypatch.setattr(UserService, "find_by_discord_id", broken)
    token = mint(empty_store)

    with caplog.at_level(logging.ERROR):
        resp = client.post("/fantasy-bet", json={"token": token})

    assert resp.status_code == 500, resp.text
    assert resp.json() == {"error": "Internal Server Error"}
    assert errors(caplog)[0].exc_info


@pytest.mark.parametrize("score", [3, -1])
def test_a_map_score_outside_the_range_answers_422(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any], score: int
) -> None:
    """A series is best of three. A score the scoring rule cannot price is
    the caller's fault, so the write model refuses it before it is stored."""
    resp = client.put(
        f"/series/{seeded['series_open_id']}",
        json={"player1_score": score},
        headers=auth_headers,
    )
    assert resp.status_code == 422
    assert "player1_score" in resp.json()["error"]


def test_a_map_score_in_the_range_is_stored(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    resp = client.put(
        f"/series/{seeded['series_open_id']}",
        json={"player1_score": 2, "player2_score": 1},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert resp.json()["player1_score"] == 2


def test_no_route_builds_an_error_body_itself() -> None:
    """The handlers in app.main own every error body, so no route writes one."""
    for module in pkgutil.iter_modules(routes.__path__):
        name = f"{routes.__name__}.{module.name}"
        source = inspect.getsource(importlib.import_module(name))
        assert 'JSONResponse({"error"' not in source, name
