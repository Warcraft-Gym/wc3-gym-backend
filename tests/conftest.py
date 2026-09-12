"""Shared fixtures. This is the only test module that touches FastAPI.

Every test asserts on status codes and JSON bodies through the client
fixture, or calls a service object directly. Nothing outside this file
imports a web framework, so a move to another one replaces the app and
client fixtures and keeps the suite.

The application and the process are one-to-one: Session.configure and the
service singletons in app/api/deps.py are process-global, so the app
fixture is session-scoped. Tests share one database file and the clean_db
fixture empties it between tests.

The suite opens no socket: no_third_party_calls fails any call the tests
did not stand in for.
"""

import io
import itertools
import os
from collections.abc import Callable, Generator
from datetime import date
from types import SimpleNamespace
from typing import Any

import openpyxl
import pytest
import requests
from fastapi import FastAPI
from httpx2 import Client

# create_app reads the process environment and no .env file, so the suite
# runs the same on every machine. The shell's own values are cleared here.
os.environ["JWT_SECRET_KEY"] = "test-secret-key-of-at-least-32-bytes"
os.environ["ADMIN_TOKEN"] = "test-admin-token"
os.environ["TOKEN_TIME"] = "15"
os.environ.pop("DB_URL", None)
os.environ.pop("SCORE_SYSTEM", None)
# A bot token would send the role sync to Discord, and the guard below fails that
os.environ.pop("DISCORD_BOT_TOKEN", None)

from app.main import create_app
from app.services import blob, r2, replays
from tests.discord import PUBLIC_KEY, Clock, record

type SheetSpec = tuple[list[str], list[list[Any]]]


def write_workbook(sheets: dict[str, SheetSpec]) -> io.BytesIO:
    """An xlsx stream with one (header, rows) sheet per entry."""
    workbook = openpyxl.Workbook()
    workbook.remove(workbook.worksheets[0])
    for name, (columns, rows) in sheets.items():
        sheet = workbook.create_sheet(name)
        sheet.append(columns)
        for row in rows:
            sheet.append(row)
    stream = io.BytesIO()
    workbook.save(stream)
    stream.seek(0)
    return stream


@pytest.fixture(scope="session")
def db_url(tmp_path_factory: pytest.TempPathFactory) -> str:
    """A migrated database. A file, not :memory:, because the migration and
    the application open their own connections to it."""
    from tests.migrate import fresh_database, upgrade_to_head

    url = fresh_database(tmp_path_factory.mktemp("db"), "test")
    upgrade_to_head(url)
    return url


@pytest.fixture(scope="session")
def app(db_url: str) -> FastAPI:
    return create_app(db_url=db_url)


@pytest.fixture
def client(app: FastAPI) -> Client:
    from fastapi.testclient import TestClient

    # follow_redirects off so a 302 is asserted as a 302. raise_server_exceptions
    # off so a route error is asserted as the 500 body a real client sees.
    return TestClient(app, follow_redirects=False, raise_server_exceptions=False)


def empty_tables() -> None:
    """Empty every table. Children first, so no foreign key constraint
    fires."""
    from sqlalchemy import text
    from sqlmodel import SQLModel

    from app.core.db import Session

    with Session() as session:
        if session.get_bind().dialect.name == "postgresql":
            # Restart the id sequences too, so ids count from 1 in every
            # test, as they do in SQLite.
            names = ", ".join(t.name for t in SQLModel.metadata.sorted_tables)
            session.execute(text(f"TRUNCATE {names} RESTART IDENTITY CASCADE"))
        else:
            for table in reversed(SQLModel.metadata.sorted_tables):
                session.execute(table.delete())
        session.commit()


@pytest.fixture(autouse=True)
def clean_db(app: FastAPI) -> Generator[None]:
    """Empty every table after each test."""
    yield
    empty_tables()


@pytest.fixture(autouse=True)
def blob_store(monkeypatch: pytest.MonkeyPatch) -> dict[str, bytes]:
    """No test uploads to Vercel Blob or R2. The uploads land in this dict instead, keyed by the
    URL the fake store answers, so a test can read back what the route stored."""
    stored: dict[str, bytes] = {}
    # a counter, not len(stored): a delete would otherwise let the next URL repeat one already used
    serial = itertools.count()

    def put_icon(name: str, data: bytes) -> str:
        # the real host, because blob.ours() reads it to tell our picture from a published one
        url = f"https://test.public.blob.vercel-storage.com/{name}-{next(serial)}.png"
        stored[url] = data
        return url

    def download_url(key: str) -> str:
        return f"https://r2.test/{key}"

    monkeypatch.setattr(blob, "put_icon", put_icon)
    monkeypatch.setattr(blob, "delete_blob", lambda url: stored.pop(url, None))

    def peek(key: str) -> tuple[bytes, int] | None:
        data = stored.get(download_url(key))
        return (data[:28], len(data)) if data is not None else None

    monkeypatch.setattr(r2, "download_url", download_url)
    monkeypatch.setattr(r2, "upload_url", lambda key: f"https://r2.test/upload/{key}")
    monkeypatch.setattr(r2, "peek", peek)
    monkeypatch.setattr(r2, "fetch", lambda key: stored[download_url(key)])
    monkeypatch.setattr(r2, "delete", lambda key: stored.pop(download_url(key), None))
    return stored


REPLAY_BYTES = replays.REPLAY_MAGIC + b"\0" * 64


@pytest.fixture
def replay_uploaded(blob_store: dict[str, bytes]) -> Callable[..., None]:
    """Pretend the browser put a replay in the bucket for these games of a series."""

    def upload(series_id: int, *games: int, data: bytes = REPLAY_BYTES) -> None:
        for game_no in games:
            blob_store[f"https://r2.test/{r2.key(series_id, game_no)}"] = data

    return upload


@pytest.fixture(autouse=True)
def no_third_party_calls(monkeypatch: pytest.MonkeyPatch) -> None:
    """No test reaches w3champions. A test that answers for it patches this
    method again, and one that forgets fails here instead of on the network."""

    def refuse(self: requests.Session, method: str, url: str, **kwargs: object) -> None:
        raise AssertionError(f"the test called out to {method} {url}")

    monkeypatch.setattr(requests.Session, "request", refuse)


@pytest.fixture
def seeded(app: FastAPI) -> dict[str, Any]:
    """A small consistent league. Returns the ids the tests refer to."""
    from app.core.db import Session
    from tests.seed import seed_league

    with Session() as session:
        ids = seed_league(session)
        session.commit()
    return ids


@pytest.fixture
def member(monkeypatch: pytest.MonkeyPatch) -> Callable[..., dict[str, str]]:
    """A factory for the headers of a signed-in guild member.

    Each Discord id is its own Clerk user, so one test acts as both players.
    """
    from clerk_backend_api import Clerk
    from clerk_backend_api.security.types import AuthStatus, RequestState
    from clerk_backend_api.users import Users
    from starlette.requests import Request

    from app.services import discord
    from tests.test_discord_auth import GUILD, GUILD_ID, FakeResponse

    accounts: dict[str, dict[str, Any]] = {}

    def authenticate_request(
        self: Clerk, request: Request, options: object
    ) -> RequestState:
        bearer = request.headers.get("authorization", "").removeprefix("Bearer ")
        if bearer not in accounts:
            return RequestState(status=AuthStatus.SIGNED_OUT)
        return RequestState(
            status=AuthStatus.SIGNED_IN, payload={"sub": f"user_{bearer}", "sid": "s"}
        )

    def oauth_token(self: Users, **kwargs: str) -> list[SimpleNamespace]:
        discord_id = kwargs["user_id"].removeprefix("user_")
        return [SimpleNamespace(token=discord_id, provider_user_id=discord_id)]

    def user_get(access_token: str, path: str) -> FakeResponse:
        return FakeResponse(200, accounts[access_token])

    def bot_get(path: str) -> FakeResponse:
        if path == f"/guilds/{GUILD_ID}":
            return FakeResponse(200, GUILD)
        return FakeResponse(200, {"roles": []})

    monkeypatch.setenv("DISCORD_GUILD_ID", GUILD_ID)
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "a-bot-token")
    monkeypatch.setenv("ADMIN_DISCORD_IDS", "")
    monkeypatch.setattr(Clerk, "authenticate_request", authenticate_request)
    monkeypatch.setattr(Users, "get_o_auth_access_token", oauth_token)
    monkeypatch.setattr(discord, "_user_get", user_get)
    monkeypatch.setattr(discord, "_bot_get", bot_get)

    def issue(discord_id: str = "1") -> dict[str, str]:
        accounts[discord_id] = {
            "id": discord_id,
            "username": f"p{discord_id}",
            "avatar": None,
        }
        return {"Authorization": f"Bearer {discord_id}"}

    return issue


@pytest.fixture
def auth_headers(client: Client) -> dict[str, str]:
    resp = client.post("/login", json={"token": "test-admin-token"})
    assert resp.status_code == 200
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


# Discord interactions
@pytest.fixture
def public_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DISCORD_PUBLIC_KEY", PUBLIC_KEY)


@pytest.fixture
def bot_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "a-bot-token")


@pytest.fixture
def discord_calls(
    monkeypatch: pytest.MonkeyPatch, bot_token: None
) -> list[tuple[str, str, Any]]:
    """Record every call to Discord and answer 200."""
    return record(monkeypatch, 200)


@pytest.fixture(autouse=True)
def checkin_day(monkeypatch: pytest.MonkeyPatch) -> Callable[[str], None]:
    """The day check-in reads. The seeded rounds run four weeks from 5 Jan 2026,
    so the default opens round 1 and round 2 and a test names another day."""
    from app.services import availability

    def on(day: str) -> None:
        monkeypatch.setattr(availability, "today", lambda: date.fromisoformat(day))

    on("2026-01-09")
    return on


@pytest.fixture(autouse=True)
def clock(monkeypatch: pytest.MonkeyPatch) -> Clock:
    """The post pacing waits on this clock, so no test sleeps for real."""
    from app.services import discord_posts

    clock = Clock()
    monkeypatch.setattr(discord_posts, "utcnow", clock.read)
    monkeypatch.setattr(discord_posts, "sleep", clock.sleep)
    return clock
