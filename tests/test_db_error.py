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
    def broken(session: Session) -> Never:
        raise OperationalError("SELECT secret FROM maps", {}, Exception("boom"))

    monkeypatch.setattr(Map, "getAll", broken)
    resp = client.get("/maps")
    assert resp.status_code == 500
    assert resp.json() == {"error": "Database error"}
