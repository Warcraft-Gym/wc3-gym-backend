"""A reported result keeps its replays: the browser puts one file per game in the bucket,
the report confirms them, one row per slot."""

from collections.abc import Callable
from typing import Any

import pytest
from httpx2 import Client, Response

from app.services import blob
from tests.conftest import REPLAY_BYTES


@pytest.fixture(autouse=True)
def no_discord(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import player_series

    monkeypatch.setattr(
        player_series, "_notify_discord_series_update", lambda *a: False
    )


def report(
    client: Client, series_id: int, token: str, p1: int = 2, p2: int = 0
) -> Response:
    return client.put(
        f"/player-series/{series_id}",
        data={
            "token": token,
            "action": "score_updated",
            "player1_score": str(p1),
            "player2_score": str(p2),
        },
    )


def test_a_report_keeps_its_replays(
    client: Client,
    seeded: dict[str, Any],
    dashboard_token: Callable[..., str],
    blob_store: dict[str, bytes],
    replay_uploaded: Callable[..., None],
) -> None:
    series_id = seeded["series_open_id"]
    replay_uploaded(series_id, 1, 2)
    resp = report(client, series_id, dashboard_token(discord_id="2"))
    assert resp.status_code == 200, resp.text
    stored = resp.json()["replays"]
    assert [r["game_no"] for r in stored] == [1, 2]
    assert all(blob_store[r["url"]] == REPLAY_BYTES for r in stored)
    assert all(r["uploaded_by"] and r["uploaded_at"] for r in stored)

    listed = client.get(f"/matches/{resp.json()['match_id']}/replays")
    assert listed.status_code == 200, listed.text
    assert listed.json() == stored


def test_a_player_gets_an_upload_link_and_a_stranger_does_not(
    client: Client, seeded: dict[str, Any], dashboard_token: Callable[..., str]
) -> None:
    series_id = seeded["series_open_id"]
    path = f"/player-series/{series_id}/replays/1/upload-url"
    resp = client.post(path, params={"token": dashboard_token(discord_id="2")})
    assert resp.status_code == 200, resp.text
    assert resp.json()["url"].endswith(f"/replays/{series_id}/game1.w3g")
    resp = client.post(path, params={"token": dashboard_token(discord_id="9")})
    assert resp.status_code in (403, 404), resp.text


def test_one_replay_is_replaced_after_the_result(
    client: Client,
    seeded: dict[str, Any],
    dashboard_token: Callable[..., str],
    blob_store: dict[str, bytes],
    replay_uploaded: Callable[..., None],
) -> None:
    series_id = seeded["series_open_id"]
    token = dashboard_token(discord_id="2")
    path = f"/player-series/{series_id}/replays/2"

    resp = client.put(path, params={"token": token})
    assert resp.status_code == 400, resp.text
    assert resp.json() == {"error": "Report the result first"}

    replay_uploaded(series_id, 1, 2)
    assert report(client, series_id, token).status_code == 200
    replay_uploaded(series_id, 2, data=REPLAY_BYTES + b"\1")
    resp = client.put(path, params={"token": token})
    assert resp.status_code == 200, resp.text
    assert resp.json()["game_no"] == 2
    assert blob_store[resp.json()["url"]] == REPLAY_BYTES + b"\1"

    resp = client.put(f"/player-series/{series_id}/replays/3", params={"token": token})
    assert resp.status_code == 400, resp.text
    assert resp.json() == {"error": "This series had 2 games"}


def test_a_file_that_is_not_a_replay_is_refused(
    client: Client,
    seeded: dict[str, Any],
    dashboard_token: Callable[..., str],
    replay_uploaded: Callable[..., None],
) -> None:
    series_id = seeded["series_open_id"]
    replay_uploaded(series_id, 1)
    replay_uploaded(series_id, 2, data=b"replay")
    resp = report(client, series_id, dashboard_token(discord_id="2"))
    assert resp.status_code == 400, resp.text
    assert resp.json()["error"] == "Game 2 is not a Warcraft III replay"
    assert client.get(f"/series/{series_id}").json()["player1_score"] is None
    listed = (
        client.get(f"/matches/{seeded['match_id']}/replays")
        if "match_id" in seeded
        else None
    )
    assert listed is None or listed.json() == []


def test_the_replays_of_a_missing_match(client: Client) -> None:
    assert client.get("/matches/999999/replays").status_code == 404


def test_a_deleted_series_or_season_drops_its_replays_from_the_store(
    client: Client,
    seeded: dict[str, Any],
    dashboard_token: Callable[..., str],
    blob_store: dict[str, bytes],
    replay_uploaded: Callable[..., None],
) -> None:
    from app.api.deps import season_service, series_service

    # each series reported by one of its own players
    for series_id, discord_id in (
        (seeded["series_open_id"], "2"),
        (seeded["series_played_id"], "1"),
    ):
        replay_uploaded(series_id, 1, 2)
        resp = report(client, series_id, dashboard_token(discord_id=discord_id))
        assert resp.status_code == 200, resp.text
    assert len(blob_store) == 4

    series_service.delete(seeded["series_open_id"])
    assert len(blob_store) == 2
    season_service.delete(seeded["season_id"])
    assert blob_store == {}


def test_a_deleted_team_drops_its_logo_and_its_replays(
    client: Client,
    seeded: dict[str, Any],
    dashboard_token: Callable[..., str],
    blob_store: dict[str, bytes],
    replay_uploaded: Callable[..., None],
) -> None:
    from app.api.deps import team_service
    from app.core.db import Session
    from app.models.team import Team

    replay_uploaded(seeded["series_open_id"], 1, 2)
    resp = report(client, seeded["series_open_id"], dashboard_token(discord_id="2"))
    assert resp.status_code == 200, resp.text
    with Session.begin() as session:
        team = session.get(Team, seeded["team_a_id"])
        assert team
        team.icon_url = blob.put_icon("teams/a", b"\x89PNG\r\n\x1a\n" + b"0" * 8)
    assert len(blob_store) == 3

    team_service.delete(seeded["team_a_id"])
    assert blob_store == {}
