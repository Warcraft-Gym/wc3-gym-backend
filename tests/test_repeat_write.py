"""A write that repeats a row another request already wrote answers success.

Each service method runs in its own transaction, so a link row can appear
between the read and the write of a concurrent request. The second write of
the same row takes the path that request takes: the database refuses the
duplicate and the service reports the row as already present.
"""

from typing import Any

import pytest
from httpx2 import Client
from sqlalchemy import func, select
from sqlalchemy.exc import SQLAlchemyError

from app.core.exceptions import NotFoundError
from app.models.settings import SettingsPublic
from app.services.settings import SettingsService


def _map_links(season_id: int) -> int:
    from app.core.db import Session
    from app.models.relationships import DBMapSeason

    with Session() as session:
        return (
            session.scalar(
                select(func.count())
                .select_from(DBMapSeason)
                .where(DBMapSeason.season_id == season_id)
            )
            or 0
        )


def test_a_map_added_twice_answers_200_and_links_once(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    body = {"map_ids": [seeded["map_id"]]}
    path = f"/seasons/{seeded['season_id']}/maps"

    first = client.post(path, json=body, headers=auth_headers)
    assert first.status_code == 200, first.text

    second = client.post(path, json=body, headers=auth_headers)
    assert second.status_code == 200, second.text
    assert [m["id"] for m in second.json()["maps"]] == [seeded["map_id"]]
    assert _map_links(seeded["season_id"]) == 1


def test_a_repeated_map_leaves_the_rest_of_the_request_alive(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    new_map = client.post(
        "/maps", json={"name": "Twisted Meadows"}, headers=auth_headers
    )
    assert new_map.status_code in (200, 201), new_map.text
    new_map_id = new_map.json()["id"]

    resp = client.post(
        f"/seasons/{seeded['season_id']}/maps",
        json={"map_ids": [seeded["map_id"], seeded["map_id"], new_map_id]},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert sorted(m["id"] for m in resp.json()["maps"]) == sorted(
        [seeded["map_id"], new_map_id]
    )
    assert _map_links(seeded["season_id"]) == 2


def test_a_new_setting_key_is_created(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    resp = client.put(
        "/config/settings/new_key", json={"value": "42"}, headers=auth_headers
    )
    assert resp.status_code == 200, resp.text

    assert client.get("/config/settings/new_key").json()["value"] == "42"


def test_a_known_setting_key_is_updated(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    resp = client.put(
        "/config/settings/score_system", json={"value": "gnl"}, headers=auth_headers
    )
    assert resp.status_code == 200, resp.text

    assert client.get("/config/settings/score_system").json()["value"] == "gnl"


def test_a_setting_key_written_by_another_request_is_updated(
    client: Client, seeded: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The read misses the key the way it misses before a concurrent insert."""
    service = SettingsService()
    read_by_key = service.get_by_key
    misses = []

    def miss_once(key: str) -> SettingsPublic:
        if not misses:
            misses.append(key)
            raise NotFoundError(f"Setting with key '{key}' not found")
        return read_by_key(key)

    monkeypatch.setattr(service, "get_by_key", miss_once)

    assert service.update_setting("score_system", "gnl")["value"] == "gnl"
    assert client.get("/config/settings/score_system").json()["value"] == "gnl"


def test_a_read_error_does_not_create_a_setting(
    client: Client, seeded: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    service = SettingsService()

    def fail(key: str) -> SettingsPublic:
        raise SQLAlchemyError("connection lost")

    monkeypatch.setattr(service, "get_by_key", fail)

    with pytest.raises(SQLAlchemyError):
        service.update_setting("new_key", "42")
    assert client.get("/config/settings/new_key").status_code == 404
