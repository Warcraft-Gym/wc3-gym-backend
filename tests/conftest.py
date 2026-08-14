"""Shared fixtures. This is the only test module that touches Flask.

Every test asserts on status codes and JSON bodies through the client
fixture, or calls a service object directly. Nothing outside this file
imports Flask, so a move to another web framework replaces the app and
client fixtures and keeps the suite.

The application and the process are one-to-one: Session.configure and the
blueprint attributes are process-global, so the app fixture is
session-scoped. Tests share one database file and the clean_db fixture
empties it between tests.
"""

import os

import pytest

# create_app reads these. Set before the src import so the values are the
# same with and without a .env file (load_dotenv does not override).
os.environ["JWT_SECRET_KEY"] = "test-secret-key-of-at-least-32-bytes"
os.environ["ADMIN_TOKEN"] = "test-admin-token"
os.environ["TOKEN_TIME"] = "15"
os.environ["REFRESH_TOKEN_TIME"] = "300"
os.environ.pop("DB_URL", None)
os.environ.pop("SCORE_SYSTEM", None)

from app.main import create_app


@pytest.fixture(scope="session")
def app(tmp_path_factory):
    # A file, not :memory:. init_schema disposes the pool, and disposing
    # the only connection of an in-memory SQLite database deletes the
    # tables with it.
    db_file = tmp_path_factory.mktemp("db") / "test.sqlite"
    return create_app(db_url=f"sqlite:///{db_file}")


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture(autouse=True)
def clean_db(app):
    """Empty every table after each test. Children first, so no foreign
    key constraint fires."""
    yield
    from app.database.engine import Session
    from app.models.base import Base

    with Session() as session:
        for table in reversed(Base.metadata.sorted_tables):
            session.execute(table.delete())
        session.commit()


@pytest.fixture
def seeded(app):
    """A small consistent league. Returns the ids the tests refer to."""
    from app.database.engine import Session
    from tests.seed import seed_league

    with Session() as session:
        ids = seed_league(session)
        session.commit()
    return ids


@pytest.fixture
def route_count(app):
    """Number of registered routes, excluding the static route. Lives here
    so the url_map stays out of the test files."""
    return len([r for r in app.url_map.iter_rules() if r.endpoint != "static"])


@pytest.fixture
def auth_headers(client):
    resp = client.post("/login", json={"token": "test-admin-token"})
    assert resp.status_code == 200
    token = resp.get_json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
