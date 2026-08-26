"""A database failure answers 500 with a fixed message.

What the database said, including the statement, must never reach a
client. The app-level SQLAlchemyError handler owns the answer, so no
route needs a catch for it.
"""

from typing import Never

import pytest
from httpx2 import Client
from sqlalchemy.exc import OperationalError
from sqlalchemy.orm import Session

from app.models.map import Map


def test_a_database_error_answers_a_fixed_message(
    client: Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    def broken(session: Session, **kwargs: object) -> Never:
        raise OperationalError("SELECT secret FROM maps", {}, Exception("boom"))

    monkeypatch.setattr(Map, "get_all", broken)
    resp = client.get("/maps")
    assert resp.status_code == 500
    assert resp.json() == {"error": "Database error"}


def test_a_delete_the_database_refuses_answers_409(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, object]
) -> None:
    """A row another row still names is a conflict, not a fault: the client
    can act on it by removing the reference first."""
    from app.core.db import Session

    with Session() as session:
        if session.get_bind().dialect.name == "sqlite":
            pytest.skip("the suite's SQLite does not enforce foreign keys")

    match, map_id = seeded["match_id"], seeded["map_id"]
    assert (
        client.put(
            f"/matches/{match}", json={"fixed_map_id": map_id}, headers=auth_headers
        ).status_code
        == 200
    )
    resp = client.delete(f"/maps/{map_id}", headers=auth_headers)
    assert resp.status_code == 409
    assert resp.json() == {"error": "Row is still referenced"}

    assert (
        client.put(
            f"/matches/{match}", json={"fixed_map_id": None}, headers=auth_headers
        ).status_code
        == 200
    )
    assert client.delete(f"/maps/{map_id}", headers=auth_headers).status_code == 204
