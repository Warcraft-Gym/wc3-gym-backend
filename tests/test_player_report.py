"""A player reports a result from the dashboard with the replays attached."""

from collections.abc import Callable
from typing import Any

import pytest
from httpx2 import Client

from app.services import blob


def test_a_report_with_its_replays_lands(
    client: Client,
    seeded: dict[str, Any],
    dashboard_token: Callable[..., str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from app.services import player_series

    monkeypatch.setattr(
        player_series, "_notify_discord_series_update", lambda *a: False
    )
    replay = ("game.w3g", blob.REPLAY_MAGIC + b"\0" * 8, "application/octet-stream")

    resp = client.put(
        f"/player-series/{seeded['series_open_id']}",
        data={
            "token": dashboard_token(discord_id="2"),
            "action": "score_updated",
            "player1_score": "2",
            "player2_score": "0",
        },
        files={"game1": replay, "game2": replay},
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert (body["player1_score"], body["player2_score"]) == (2, 0)
    assert body["uploaded_files"] == {"game1": "game.w3g", "game2": "game.w3g"}
