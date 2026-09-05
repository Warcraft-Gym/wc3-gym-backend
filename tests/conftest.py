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
from datetime import UTC, datetime, timedelta
from typing import Any

import openpyxl
import pytest
import requests
from fastapi import FastAPI
from httpx2 import Client

# create_app reads these. Set before the app import so the values are the
# same with and without a .env file (load_dotenv does not override).
os.environ["JWT_SECRET_KEY"] = "test-secret-key-of-at-least-32-bytes"
os.environ["ADMIN_TOKEN"] = "test-admin-token"
os.environ["TOKEN_TIME"] = "15"
os.environ.pop("DB_URL", None)
os.environ.pop("SCORE_SYSTEM", None)

from app.main import create_app
from app.services import blob, r2

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
    monkeypatch.setattr(
        r2, "put", lambda key, data: stored.__setitem__(download_url(key), data)
    )
    monkeypatch.setattr(r2, "download_url", download_url)
    return stored


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
def dashboard_token() -> Generator[Callable[..., str]]:
    """A factory for dashboard tokens of a seeded player."""
    from app.api.routes.public import _token_store

    issued: list[str] = []

    def issue(discord_id: str = "1", season_id: int | None = 1) -> str:
        token = f"dashboard-token-{len(issued)}"
        _token_store[token] = {
            "discord_id": discord_id,
            "discord_tag": f"p{discord_id}",
            "season_id": str(season_id) if season_id else None,
            "access_type": "dashboard",
            "expires_at": datetime.now(UTC) + timedelta(minutes=5),
        }
        issued.append(token)
        return token

    yield issue
    for token in issued:
        _token_store.pop(token, None)


@pytest.fixture
def auth_headers(client: Client) -> dict[str, str]:
    resp = client.post("/login", json={"token": "test-admin-token"})
    assert resp.status_code == 200
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
