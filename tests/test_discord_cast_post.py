"""A claim posts the match card in the content channel, and a job calls the
audience to the stream shortly before the series starts."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx2 import Client

from app.core.db import Session
from app.models.series import Series
from app.models.settings import Settings
from app.services import discord, wake
from tests.test_discord_auth import SESSION, stub_login

CONTENT = f"{discord.API_URL}/channels/content/messages"
JOB = "/jobs/cast-reminders"
SECRET = {"Authorization": "Bearer cast-secret"}
TWITCH = "twitch.tv/gnlcaster"
# The counts of a run that posts nothing
NOTHING = {"posted": 0, "late": 0, "missed": 0, "cup_reminders": 0}


def as_member(monkeypatch: pytest.MonkeyPatch, discord_id: str) -> None:
    """A Discord session of the seeded player with that Discord id."""
    stub_login(monkeypatch, account={"id": discord_id, "username": f"p{discord_id}"})


def claim(client: Client, series_id: int, **body: str) -> None:
    resp = client.post(
        f"/series/{series_id}/casts",
        json={"channel_url": TWITCH, **body},
        headers=SESSION,
    )
    assert resp.status_code == 201, resp.text


def counts(body: dict[str, Any]) -> dict[str, Any]:
    """The reply without next_run, which moves with the clock."""
    return {key: value for key, value in body.items() if key != "next_run"}


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
    monkeypatch.setenv("CLOUDFLARE_CRON_SECRET", "cast-secret")


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
    # The claim card tags nobody: nothing on it asks for an answer now
    assert card["content"] == ""
    description = card["embeds"][0]["description"]
    assert "**Casts**\n- <https://twitch.tv/gnlcaster> · P1" in description
    assert description.endswith(
        "Players: message each caster before the start and share the game name."
    )

    discord_calls.clear()
    as_member(monkeypatch, "3")
    claim(client, series_id)
    assert [call[:2] for call in discord_calls] == [("PATCH", f"{CONTENT}/msg-1")]
    assert (
        "- <https://twitch.tv/gnlcaster> · P1\n- <https://twitch.tv/gnlcaster> · P3"
        in discord_calls[0][2]["embeds"][0]["description"]
    )


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
    assert "**Casts**" not in discord_calls[0][2]["embeds"][0]["description"]


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
    # Due five minutes before the claim: owed since the claim, so not late
    assert counts(resp.json()) == {
        "posted": 1,
        "late": 0,
        "missed": 0,
        "cup_reminders": 0,
    }
    assert [call[:2] for call in discord_calls] == [("POST", CONTENT)] * 2
    reminder = discord_calls[1][2]
    # The players are called to the game, and to wait for the caster, who is tagged too
    assert reminder["content"].startswith("<@2> <@4>, your game starts <t:")
    assert reminder["content"].endswith(
        ":R>. Wait for your casters, <@1>, before you start."
    )
    description = reminder["embeds"][0]["description"]
    assert "**Casts**\n- <https://twitch.tv/gnlcaster> · P1" in description

    # A run every few minutes posts the card once, not once a run
    assert counts(client.get(JOB, headers=SECRET).json()) == NOTHING
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

    assert counts(client.get(JOB, headers=SECRET).json()) == NOTHING
    # A series nobody claimed is never announced, however close it is
    starts_in(seeded["series_played_id"], 5)
    assert counts(client.get(JOB, headers=SECRET).json()) == NOTHING
    assert len(discord_calls) == 1


def test_the_job_answers_only_the_scheduler(
    client: Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    assert client.get(JOB).status_code == 503  # CLOUDFLARE_CRON_SECRET is not set
    monkeypatch.setenv("CLOUDFLARE_CRON_SECRET", "cast-secret")
    monkeypatch.setenv("CRON_SECRET", "cron-secret")
    assert client.get(JOB).status_code == 401
    # The Vercel cron's secret opens every job but this one
    assert (
        client.get(JOB, headers={"Authorization": "Bearer cron-secret"}).status_code
        == 401
    )
    assert client.get(JOB, headers={"Authorization": "Bearer nope"}).status_code == 401
    assert client.get(JOB, headers=SECRET).status_code == 200


def next_run(client: Client) -> timedelta:
    """How far ahead the job tells the Worker to call it again."""
    body = client.get(JOB, headers=SECRET).json()
    return datetime.fromisoformat(body["next_run"]) - datetime.now(UTC)


def test_the_job_names_its_next_run(
    client: Client,
    discord_calls: list,
    seeded: dict[str, Any],
    content_channel: None,
    cron: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    # Nothing is scheduled: the Worker sleeps the longest it may
    assert wake.FLOOR - timedelta(minutes=1) < next_run(client) <= wake.FLOOR

    series_id = seeded["series_open_id"]
    starts_in(series_id, 40)
    as_member(monkeypatch, "1")
    claim(client, series_id)
    # The card falls due REMINDER_LEAD before the start
    assert timedelta(minutes=24) < next_run(client) <= timedelta(minutes=25)

    starts_in(series_id, 10)
    assert client.get(JOB, headers=SECRET).json()["posted"] == 1
    # A series that has its card no longer holds the Worker awake
    assert next_run(client) > wake.FLOOR - timedelta(minutes=1)
