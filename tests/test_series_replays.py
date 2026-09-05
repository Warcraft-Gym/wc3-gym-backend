"""A reported result keeps its replays: one file per game, one row per slot."""

from collections.abc import Callable
from typing import Any

import pytest
from httpx2 import Client, Response

from app.services import blob, replays

REPLAY = replays.REPLAY_MAGIC + b"\0" * 64
FILE = ("game.w3g", REPLAY, "application/octet-stream")


@pytest.fixture(autouse=True)
def no_discord(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import player_series

    monkeypatch.setattr(
        player_series, "_notify_discord_series_update", lambda *a: False
    )


def report(
    client: Client, series_id: int, token: str, files: dict[str, Any]
) -> Response:
    return client.put(
        f"/player-series/{series_id}",
        data={
            "token": token,
            "action": "score_updated",
            "player1_score": "2",
            "player2_score": "0",
        },
        files=files,
    )


def test_a_report_keeps_its_replays(
    client: Client,
    seeded: dict[str, Any],
    dashboard_token: Callable[..., str],
    blob_store: dict[str, bytes],
) -> None:
    series_id = seeded["series_open_id"]
    resp = report(
        client,
        series_id,
        dashboard_token(discord_id="2"),
        {"game1": FILE, "game2": FILE},
    )
    assert resp.status_code == 200, resp.text
    stored = resp.json()["replays"]
    assert [r["game_no"] for r in stored] == [1, 2]
    assert all(blob_store[r["url"]] == REPLAY for r in stored)
    assert all(r["uploaded_by"] and r["uploaded_at"] for r in stored)

    listed = client.get(f"/matches/{resp.json()['match_id']}/replays")
    assert listed.status_code == 200, listed.text
    assert listed.json() == stored


def test_a_second_upload_replaces_the_first(
    client: Client,
    seeded: dict[str, Any],
    dashboard_token: Callable[..., str],
    blob_store: dict[str, bytes],
) -> None:
    series_id = seeded["series_open_id"]
    token = dashboard_token(discord_id="2")
    report(client, series_id, token, {"game1": FILE, "game2": FILE})
    longer = ("game.w3g", REPLAY + b"\1", "application/octet-stream")
    second = report(
        client, series_id, token, {"game1": longer, "game2": longer}
    ).json()["replays"]
    assert set(blob_store) == {r["url"] for r in second}
    assert all(blob_store[r["url"]] == REPLAY + b"\1" for r in second)


def test_a_file_that_is_not_a_replay_is_refused(
    client: Client,
    seeded: dict[str, Any],
    dashboard_token: Callable[..., str],
    blob_store: dict[str, bytes],
) -> None:
    series_id = seeded["series_open_id"]
    bad = ("game.w3g", b"replay", "application/octet-stream")
    resp = report(
        client,
        series_id,
        dashboard_token(discord_id="2"),
        {"game1": FILE, "game2": bad},
    )
    assert resp.status_code == 400, resp.text
    assert resp.json()["error"] == "Not a Warcraft III replay"
    assert blob_store == {}
    assert client.get(f"/series/{series_id}").json()["player1_score"] is None


def test_the_replays_of_a_missing_match(client: Client) -> None:
    assert client.get("/matches/999999/replays").status_code == 404


def test_a_deleted_series_or_season_drops_its_replays_from_the_store(
    client: Client,
    seeded: dict[str, Any],
    dashboard_token: Callable[..., str],
    blob_store: dict[str, bytes],
) -> None:
    from app.api.deps import season_service, series_service

    # each series reported by one of its own players
    for series_id, discord_id in (
        (seeded["series_open_id"], "2"),
        (seeded["series_played_id"], "1"),
    ):
        token = dashboard_token(discord_id=discord_id)
        resp = report(client, series_id, token, {"game1": FILE, "game2": FILE})
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
) -> None:
    from app.api.deps import team_service
    from app.core.db import Session
    from app.models.team import Team

    resp = report(
        client,
        seeded["series_open_id"],
        dashboard_token(discord_id="2"),
        {"game1": FILE, "game2": FILE},
    )
    assert resp.status_code == 200, resp.text
    with Session.begin() as session:
        team = session.get(Team, seeded["team_a_id"])
        assert team
        team.icon_url = blob.put_icon("teams/a", b"\x89PNG\r\n\x1a\n" + b"0" * 8)
    assert len(blob_store) == 3

    team_service.delete(seeded["team_a_id"])
    assert blob_store == {}
