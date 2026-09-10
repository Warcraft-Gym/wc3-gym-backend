"""A claim posts the match card in the content channel, and a job calls the
audience to the stream shortly before the series starts."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx2 import Client

from app.core.db import Session
from app.models.series import Series
from app.models.settings import Settings
from app.services import discord
from tests.test_discord_auth import SESSION, stub_clerk

CONTENT = f"{discord.API_URL}/channels/content/messages"
JOB = "/jobs/cast-reminders"
SECRET = {"Authorization": "Bearer cron-secret"}
TWITCH = "twitch.tv/gnlcaster"


def as_member(monkeypatch: pytest.MonkeyPatch, discord_id: str) -> None:
    """A Clerk session of the seeded player with that Discord id."""
    stub_clerk(monkeypatch, account={"id": discord_id, "username": f"p{discord_id}"})


def claim(client: Client, series_id: int, **body: str) -> None:
    resp = client.post(
        f"/series/{series_id}/casts",
        json={"channel_url": TWITCH, **body},
        headers=SESSION,
    )
    assert resp.status_code == 201, resp.text


def starts_in(series_id: int, minutes: float) -> None:
    with Session.begin() as session:
        series = session.get(Series, series_id)
        assert series
        series.date_time = datetime.now(UTC) + timedelta(minutes=minutes)


@pytest.fixture
def content_channel() -> None:
    with Session.begin() as session:
        session.add(Settings(key="content_channel_id", value="content"))


@pytest.fixture
def cron(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CRON_SECRET", "cron-secret")


def test_a_claim_posts_the_card_and_a_second_claim_edits_it(
    client: Client,
    discord_calls: list,
    seeded: dict[str, Any],
    content_channel: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    series_id = seeded["series_open_id"]
    as_member(monkeypatch, "1")
    claim(client, series_id)

    assert [call[:2] for call in discord_calls] == [("POST", CONTENT)]
    card = discord_calls[0][2]
    assert card["content"] == "<@2> vs <@4>"
    description = card["embeds"][0]["description"]
    assert "https://twitch.tv/gnlcaster" in description
    assert description.endswith(
        "P1 casts this series. Both players: message the caster before the"
        " start and share the game name."
    )

    discord_calls.clear()
    as_member(monkeypatch, "3")
    claim(client, series_id)
    assert [call[:2] for call in discord_calls] == [("PATCH", f"{CONTENT}/msg-1")]
    assert "P1, P3 casts this series" in discord_calls[0][2]["embeds"][0]["description"]


def test_an_unclaim_drops_the_caster_from_the_card(
    client: Client,
    discord_calls: list,
    seeded: dict[str, Any],
    content_channel: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    series_id = seeded["series_open_id"]
    as_member(monkeypatch, "1")
    claim(client, series_id)
    cast_id = client.get(f"/series/{series_id}/casts").json()[0]["id"]

    discord_calls.clear()
    resp = client.delete(f"/series/{series_id}/casts/{cast_id}", headers=SESSION)
    assert resp.status_code == 204, resp.text
    assert [call[:2] for call in discord_calls] == [("PATCH", f"{CONTENT}/msg-1")]
    assert "casts this series" not in discord_calls[0][2]["embeds"][0]["description"]


def test_a_claim_posts_nothing_without_the_setting_or_after_the_series(
    client: Client,
    discord_calls: list,
    seeded: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    as_member(monkeypatch, "1")
    claim(client, seeded["series_open_id"])
    assert discord_calls == []  # no content_channel_id row

    with Session.begin() as session:
        session.add(Settings(key="content_channel_id", value="content"))
    # A series that is over is claimed for its VOD alone: there is nothing to announce
    claim(client, seeded["series_played_id"], vod_url="twitch.tv/videos/123")
    assert discord_calls == []


def test_the_reminder_calls_the_audience_once(
    client: Client,
    discord_calls: list,
    seeded: dict[str, Any],
    content_channel: None,
    cron: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    series_id = seeded["series_open_id"]
    starts_in(series_id, 10)
    as_member(monkeypatch, "1")
    claim(client, series_id)  # the claim card, then the audience card

    resp = client.get(JOB, headers=SECRET)
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"posted": 1}
    assert [call[:2] for call in discord_calls] == [("POST", CONTENT)] * 2
    lines = discord_calls[1][2]["content"].splitlines()
    assert lines[0].startswith("P2 vs P4 starts <t:")
    assert lines[0].endswith(">, cast by P1")
    assert lines[1] == "<https://twitch.tv/gnlcaster>"

    # A run every few minutes posts the card once, not once a run
    assert client.get(JOB, headers=SECRET).json() == {"posted": 0}
    assert len(discord_calls) == 2


def test_the_reminder_skips_a_series_that_is_not_due(
    client: Client,
    discord_calls: list,
    seeded: dict[str, Any],
    content_channel: None,
    cron: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    series_id = seeded["series_open_id"]
    starts_in(series_id, 90)
    as_member(monkeypatch, "1")
    claim(client, series_id)  # the claim card alone
    assert len(discord_calls) == 1

    assert client.get(JOB, headers=SECRET).json() == {"posted": 0}
    # A series nobody claimed is never announced, however close it is
    starts_in(seeded["series_played_id"], 5)
    assert client.get(JOB, headers=SECRET).json() == {"posted": 0}
    assert len(discord_calls) == 1


def test_the_job_answers_only_the_scheduler(
    client: Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert client.get(JOB).status_code == 503  # CRON_SECRET is not set
    monkeypatch.setenv("CRON_SECRET", "cron-secret")
    assert client.get(JOB).status_code == 401
    assert client.get(JOB, headers={"Authorization": "Bearer nope"}).status_code == 401
    assert client.get(JOB, headers=SECRET).status_code == 200
