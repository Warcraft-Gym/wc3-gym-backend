"""A score write posts the result card in the results channel once, and a
corrected score edits that post. The card hides the score and every game's
replay behind a spoiler, the third game too, so the count gives nothing away."""

from collections.abc import Callable
from typing import Any

import pytest
from httpx2 import Client

from app.core.db import Session
from app.models.series import Series
from app.models.series_cast import SeriesCast
from app.models.settings import Settings
from app.services import discord

RESULTS = f"{discord.API_URL}/channels/results/messages"


def report(
    client: Client, series_id: int, headers: dict[str, str], p1: int, p2: int
) -> None:
    resp = client.put(
        f"/player-series/{series_id}",
        headers=headers,
        data={
            "action": "score_updated",
            "player1_score": str(p1),
            "player2_score": str(p2),
        },
    )
    assert resp.status_code == 200, resp.text


@pytest.fixture
def results_channel() -> None:
    with Session.begin() as session:
        session.add(Settings(key="results_channel_id", value="results"))


def test_a_result_posts_once_and_a_correction_edits_it(
    client: Client,
    discord_calls: list,
    seeded: dict[str, Any],
    member: Callable[..., dict[str, str]],
    replay_uploaded: Callable[..., None],
    results_channel: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("FRONTEND_URL", "https://gnl.test/")
    series_id = seeded["series_open_id"]
    with Session.begin() as session:
        series = session.get(Series, series_id)
        assert series
        series.casts.append(
            SeriesCast(
                channel_url="https://twitch.tv/gnlcaster",
                vod_url="https://www.twitch.tv/videos/123",
            )
        )
    headers = member("2")
    replay_uploaded(series_id, 1, 2)
    report(client, series_id, headers, 2, 0)
    assert [call[:2] for call in discord_calls] == [("POST", RESULTS)]
    card = discord_calls[0][2]
    assert card["content"] == ""
    lines = card["embeds"][0]["description"].splitlines()
    assert lines[0] == "## Season 1"
    assert lines[1].startswith("Round 1")
    assert lines[3] == "### Team Alpha (Alpha) vs Team Beta (Beta)"
    assert lines[4] == (
        "🇺🇸 **[P2](<https://gnl.test/player/P2%232222>)**"
        " vs 🇸🇪 **[P4](<https://gnl.test/player/P4%234444>)**"
    )
    assert lines[6] == "**Result** ||P2 2-0 P4||"
    replay = f"https://r2.test/development/replays/{series_id}"
    assert lines[7:10] == [
        f"Game 1 · ||[Download replay](<{replay}/game1.w3g>)||",
        f"Game 2 · ||[Download replay](<{replay}/game2.w3g>)||",
        "Game 3 · ||Game not played||",
    ]
    assert lines[11:13] == [
        "**VODs**",
        "- <https://www.twitch.tv/videos/123> · twitch.tv/gnlcaster",
    ]
    assert lines[14] == f"[Match page](<https://gnl.test/match/{seeded['match_id']}>)"
    assert card["embeds"][0]["footer"]["text"] == "MMR not synced yet"

    discord_calls.clear()
    replay_uploaded(series_id, 3)
    report(client, series_id, headers, 2, 1)
    assert [call[:2] for call in discord_calls] == [("PATCH", f"{RESULTS}/msg-1")]
    lines = discord_calls[0][2]["embeds"][0]["description"].splitlines()
    assert lines[6] == "**Result** ||P2 2-1 P4||"
    assert lines[9] == f"Game 3 · ||[Download replay](<{replay}/game3.w3g>)||"


def test_the_same_score_again_and_no_setting_post_nothing(
    client: Client,
    discord_calls: list,
    seeded: dict[str, Any],
    member: Callable[..., dict[str, str]],
    replay_uploaded: Callable[..., None],
) -> None:
    series_id = seeded["series_open_id"]
    replay_uploaded(series_id, 1, 2)
    report(client, series_id, member("2"), 2, 0)
    assert discord_calls == []
