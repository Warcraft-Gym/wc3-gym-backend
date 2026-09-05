"""A player reports a result from the dashboard once the replays are in the bucket."""

from collections.abc import Callable
from typing import Any

import pytest
from httpx2 import Client


@pytest.fixture(autouse=True)
def no_discord(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import player_series

    monkeypatch.setattr(
        player_series, "_notify_discord_series_update", lambda *a: False
    )


def test_a_report_with_its_replays_lands(
    client: Client,
    seeded: dict[str, Any],
    dashboard_token: Callable[..., str],
    replay_uploaded: Callable[..., None],
) -> None:
    replay_uploaded(seeded["series_open_id"], 1, 2)
    resp = client.put(
        f"/player-series/{seeded['series_open_id']}",
        data={
            "token": dashboard_token(discord_id="2"),
            "action": "score_updated",
            "player1_score": "2",
            "player2_score": "0",
        },
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert (body["player1_score"], body["player2_score"]) == (2, 0)
    assert [r["game_no"] for r in body["replays"]] == [1, 2]


def test_a_report_needs_one_replay_per_game_played(
    client: Client,
    seeded: dict[str, Any],
    dashboard_token: Callable[..., str],
    replay_uploaded: Callable[..., None],
) -> None:
    """A 2-1 went three games, so a report with two replays in the bucket is refused."""
    replay_uploaded(seeded["series_open_id"], 1, 2)
    resp = client.put(
        f"/player-series/{seeded['series_open_id']}",
        data={
            "token": dashboard_token(discord_id="2"),
            "action": "score_updated",
            "player1_score": "2",
            "player2_score": "1",
        },
    )

    assert resp.status_code == 400, resp.text
    assert resp.json() == {"error": "Game 3 replay is missing"}
