"""A score write posts the result card in the results channel once, and a
corrected score edits that post."""

from collections.abc import Callable
from typing import Any

import pytest
from httpx2 import Client

from app.core.db import Session
from app.models.settings import Settings
from app.services import discord

RESULTS = f"{discord.API_URL}/channels/results/messages"


def report(client: Client, series_id: int, token: str, p1: int, p2: int) -> None:
    resp = client.put(
        f"/player-series/{series_id}",
        data={
            "token": token,
            "action": "score_updated",
            "player1_score": str(p1),
            "player2_score": str(p2),
        },
    )
    assert resp.status_code == 200, resp.text


@pytest.fixture
def results_channel() -> None:
    with Session.begin() as session:
        session.add(Settings(key="discord_results_channel_id", value="results"))


def test_a_result_posts_once_and_a_correction_edits_it(
    client: Client,
    discord_calls: list,
    seeded: dict[str, Any],
    dashboard_token: Callable[..., str],
    replay_uploaded: Callable[..., None],
    results_channel: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FRONTEND_URL", "https://gnl.test/")
    series_id = seeded["series_open_id"]
    token = dashboard_token(discord_id="2")
    replay_uploaded(series_id, 1, 2)
    report(client, series_id, token, 2, 0)
    assert [call[:2] for call in discord_calls] == [("POST", RESULTS)]
    lines = discord_calls[0][2]["content"].splitlines()
    assert lines[0] == f"P2 2-0 P4 · Wk 1 · #{series_id}"
    assert lines[1:3] == [
        f"Game 1: https://r2.test/development/replays/{series_id}/game1.w3g",
        f"Game 2: https://r2.test/development/replays/{series_id}/game2.w3g",
    ]
    assert lines[3] == f"https://gnl.test/match/{seeded['match_id']}"
    assert lines[4].startswith("Updated <t:")

    discord_calls.clear()
    replay_uploaded(series_id, 3)
    report(client, series_id, token, 2, 1)
    assert [call[:2] for call in discord_calls] == [("PATCH", f"{RESULTS}/msg-1")]
    lines = discord_calls[0][2]["content"].splitlines()
    assert lines[0] == f"P2 2-1 P4 · Wk 1 · #{series_id}"
    assert len(lines) == 6


def test_the_same_score_again_and_no_setting_post_nothing(
    client: Client,
    discord_calls: list,
    seeded: dict[str, Any],
    dashboard_token: Callable[..., str],
    replay_uploaded: Callable[..., None],
) -> None:
    series_id = seeded["series_open_id"]
    replay_uploaded(series_id, 1, 2)
    report(client, series_id, dashboard_token(discord_id="2"), 2, 0)
    assert discord_calls == []
