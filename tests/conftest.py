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

import os
from typing import Any

import pytest
import requests
from fastapi import FastAPI
from httpx2 import Client

# create_app reads these. Set before the app import so the values are the
# same with and without a .env file (load_dotenv does not override).
os.environ["JWT_SECRET_KEY"] = "test-secret-key-of-at-least-32-bytes"
os.environ["ADMIN_TOKEN"] = "test-admin-token"
os.environ["TOKEN_TIME"] = "15"
os.environ["REFRESH_TOKEN_TIME"] = "300"
os.environ.pop("DB_URL", None)
os.environ.pop("SCORE_SYSTEM", None)

from app.main import create_app


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
def clean_db(app: FastAPI) -> None:
    """Empty every table after each test."""
    yield
    empty_tables()


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
def auth_headers(client: Client) -> dict[str, str]:
    resp = client.post("/login", json={"token": "test-admin-token"})
    assert resp.status_code == 200
    token = resp.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
