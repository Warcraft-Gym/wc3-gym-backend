"""The interactions route: Discord's signature is the auth, and a command
answers through the interaction token, never through the route's own body."""

from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
import requests
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from httpx2 import Client

from app.core.db import Session
from app.models.season import SeasonPublic
from app.models.series import Series
from app.models.series_cast import SeriesCast
from app.models.types import utcnow
from app.services import discord, interactions
from app.services.commands import base
from tests.discord import (
    APP_ID,
    CHANNEL,
    WEBHOOK,
    autocomplete,
    command,
    record,
    signed,
)
from tests.test_ladder_read import INSIDE, add_match, sign_up


def test_no_public_key_answers_503(
    client: Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DISCORD_PUBLIC_KEY", raising=False)
    body, headers = signed({"type": 1})
    resp = client.post("/discord/interactions", content=body, headers=headers)
    assert resp.status_code == 503
    assert resp.json() == {"error": "DISCORD_PUBLIC_KEY is not set"}


def test_bad_signature_answers_401(client: Client, public_key: None) -> None:
    body, headers = signed({"type": 1}, Ed25519PrivateKey.generate())
    resp = client.post("/discord/interactions", content=body, headers=headers)
    assert resp.status_code == 401
    assert resp.json() == {"error": "bad signature"}


def test_ping_answers_pong(client: Client, public_key: None) -> None:
    body, headers = signed({"type": 1})
    resp = client.post("/discord/interactions", content=body, headers=headers)
    assert resp.status_code == 200
    assert resp.json() == {"type": 1}


def test_upcoming_marks_a_cast_series_that_is_on_now(
    client: Client, public_key: None, discord_calls: list, seeded: dict[str, Any]
) -> None:
    """A claimed series inside its window gets the red dot; the same series a day out does not."""
    soon = utcnow() + timedelta(minutes=10)
    with Session.begin() as session:
        series = session.get(Series, seeded["series_open_id"])
        assert series
        series.date_time = soon
        series.casts.append(SeriesCast(channel_url="https://www.twitch.tv/gnlcaster"))
    body, headers = signed(command("upcoming"))
    assert (
        client.post("/discord/interactions", content=body, headers=headers).status_code
        == 200
    )
    line = discord_calls[0][2]["embeds"][0]["description"]
    assert line.startswith(f"🔴 <t:{int(soon.timestamp())}:f> · Wk 1 · ")


def test_upcoming_posts_the_window_publicly(
    client: Client, public_key: None, discord_calls: list, seeded: dict[str, Any]
) -> None:
    soon = utcnow() + timedelta(days=2)
    with Session.begin() as session:
        series = session.get(Series, seeded["series_open_id"])
        assert series
        series.date_time = soon
        series.casts.append(SeriesCast(channel_url="https://www.twitch.tv/gnlcaster"))
    body, headers = signed(command("upcoming"))
    resp = client.post("/discord/interactions", content=body, headers=headers)
    assert resp.status_code == 200
    assert resp.json() == {"ok": True}
    (post, delete) = discord_calls
    assert post[:2] == ("POST", CHANNEL)
    line = post[2]["embeds"][0]["description"]
    assert line == (
        f"<t:{int(soon.timestamp())}:f> · Wk 1 · P2 (Alpha) vs P4 (Beta)"
        f" · twitch.tv/gnlcaster · #{seeded['series_open_id']}"
    )
    assert delete[:2] == ("DELETE", f"{WEBHOOK}/messages/@original")


def test_upcoming_window_and_fantasy_filter(
    client: Client, public_key: None, discord_calls: list, seeded: dict[str, Any]
) -> None:
    with Session.begin() as session:
        series = session.get(Series, seeded["series_open_id"])
        assert series
        series.date_time = utcnow() + timedelta(days=10)
    body, headers = signed(command("upcoming", days=3))
    client.post("/discord/interactions", content=body, headers=headers)
    assert discord_calls[0][2] == {"content": "No series in the next 3 days."}
    body, headers = signed(command("upcoming", days=30, fantasy=True))
    client.post("/discord/interactions", content=body, headers=headers)
    assert discord_calls[2][2] == {"content": "No series in the next 30 days."}
    body, headers = signed(command("upcoming", days=30))
    client.post("/discord/interactions", content=body, headers=headers)
    assert "Wk 1" in discord_calls[4][2]["embeds"][0]["description"]


def test_leaderboard_ranks_badge_points_then_ladder_points(
    client: Client, public_key: None, discord_calls: list, seeded: dict[str, Any]
) -> None:
    """Two rostered players: the first wins twice, the second loses once."""
    first, second = seeded["player_ids"][:2]
    sign_up(seeded["season_id"], [first, second])
    add_match(first, "w1", won=True)
    add_match(first, "w2", won=True, start_time=INSIDE + timedelta(minutes=1))
    add_match(second, "l1", won=False)

    body, headers = signed(command("leaderboard"))
    assert client.post(
        "/discord/interactions", content=body, headers=headers
    ).json() == {"ok": True}
    (post, delete) = discord_calls
    assert post[:2] == ("POST", CHANNEL)
    embed = post[2]["embeds"][0]
    assert embed["title"].endswith("achievements leaderboard")
    span, blank, *lines = embed["description"].splitlines()
    # The seeded season is over, so the header names its range and says so
    assert (span, blank) == ("2026-01-05 to 2026-02-27 · ended", "")
    # The first win, the early bird and the hat-trick's opener pay the winner;
    # the loser gets the first loss's five points
    assert (
        lines[0].startswith("**1.**")
        and "(Alpha)" in lines[0]
        and " pts · " in lines[0]
    )
    assert len(lines) == 2
    assert embed["fields"][0]["name"] == "Teams"
    # The data time is the roster's oldest sync stamp; none is stored here
    assert embed["footer"] == {"text": "Ladder sync incomplete as of"}
    assert embed["timestamp"].endswith("+00:00")
    assert delete[:2] == ("DELETE", f"{WEBHOOK}/messages/@original")

    body, headers = signed(command("leaderboard", kind="ladder", top=1))
    client.post("/discord/interactions", content=body, headers=headers)
    lines = discord_calls[2][2]["embeds"][0]["description"].splitlines()
    assert lines[2:] == ["**1.** P1 (Alpha) · 6 pts · 2-0"]


def test_season_span_counts_the_weeks_of_the_range(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A 59-day window is 9 weeks however many it plays; day 27 is week 4."""
    monkeypatch.setattr(base, "utcnow", lambda: datetime(2026, 9, 6, 12, tzinfo=UTC))
    season = SeasonPublic(
        id=5,
        name="Review",
        number_weeks=4,
        series_per_week=1,
        start_date=date(2026, 8, 10),
        end_date=date(2026, 10, 7),
    )
    assert base.season_span(season) == "2026-08-10 to 2026-10-07 · week 4 of 9"
    season.start_date = date(2026, 9, 7)
    assert base.season_span(season) == "2026-09-07 to 2026-10-07"


def test_leaderboard_fantasy_ranks_the_seasons_fantasy_teams(
    client: Client, public_key: None, discord_calls: list, seeded: dict[str, Any]
) -> None:
    body, headers = signed(command("leaderboard", kind="fantasy"))
    client.post("/discord/interactions", content=body, headers=headers)
    post = discord_calls[0]
    assert post[:2] == ("POST", CHANNEL)
    embed = post[2]["embeds"][0]
    assert embed["title"].endswith("fantasy leaderboard")
    span, blank, first = embed["description"].splitlines()
    assert (span, blank) == ("2026-01-05 to 2026-02-27 · ended", "")
    assert first.startswith("**1.** The Optimists · P1 · ")
    assert first.endswith(" pts")
    assert "fields" not in embed
    assert embed["footer"] == {"text": "Standings as of"}


def test_leaderboard_names_a_season_or_says_which_is_missing(
    client: Client, public_key: None, discord_calls: list, seeded: dict[str, Any]
) -> None:
    body, headers = signed(command("leaderboard", season="nothing like it"))
    client.post("/discord/interactions", content=body, headers=headers)
    assert discord_calls[0][2] == {"content": "No season named nothing like it."}
    body, headers = signed(command("leaderboard", season="season"))
    client.post("/discord/interactions", content=body, headers=headers)
    assert "No ladder games in" in discord_calls[2][2]["content"]


def test_upcoming_stays_private_without_a_bot_token_or_when_refused(
    client: Client, public_key: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
    calls = record(monkeypatch, 200)
    body, headers = signed(command("upcoming"))
    client.post("/discord/interactions", content=body, headers=headers)
    assert [(c[0], c[1]) for c in calls] == [("PATCH", f"{WEBHOOK}/messages/@original")]
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "a-bot-token")
    calls = record(monkeypatch, 403)
    client.post("/discord/interactions", content=body, headers=headers)
    assert [(c[0], c[1]) for c in calls] == [
        ("POST", CHANNEL),
        ("PATCH", f"{WEBHOOK}/messages/@original"),
    ]


def test_unknown_command_edits_the_private_reply(
    client: Client, public_key: None, discord_calls: list
) -> None:
    body, headers = signed(command("nothing"))
    assert (
        client.post("/discord/interactions", content=body, headers=headers).status_code
        == 200
    )
    assert discord_calls == [
        ("PATCH", f"{WEBHOOK}/messages/@original", {"content": "Unknown command."})
    ]


def test_autocomplete_lists_the_callers_own_series(
    client: Client, public_key: None, seeded: dict[str, Any]
) -> None:
    body, headers = signed(autocomplete("schedule", "2", ""))
    resp = client.post("/discord/interactions", content=body, headers=headers)
    assert resp.json() == {
        "type": 8,
        "data": {
            "choices": [
                {
                    "name": f"Wk 1 · P2 (Alpha) vs P4 (Beta) · #{seeded['series_open_id']}",
                    "value": seeded["series_open_id"],
                }
            ]
        },
    }
    body, headers = signed(autocomplete("schedule", "2", "zzz"))
    resp = client.post("/discord/interactions", content=body, headers=headers)
    assert resp.json() == {"type": 8, "data": {"choices": []}}
    body, headers = signed(autocomplete("nothing", "2", ""))
    resp = client.post("/discord/interactions", content=body, headers=headers)
    assert resp.json() == {"type": 8, "data": {"choices": []}}


def test_schedule_sets_the_time_and_posts_publicly(
    client: Client, public_key: None, discord_calls: list, seeded: dict[str, Any]
) -> None:
    series_id = seeded["series_open_id"]
    body, headers = signed(
        command("schedule", user="2", series=series_id, when_utc="2026-09-09 20:00")
    )
    resp = client.post("/discord/interactions", content=body, headers=headers)
    assert resp.json() == {"ok": True}
    with Session.begin() as session:
        series = session.get(Series, series_id)
        assert series
        assert series.date_time == datetime(2026, 9, 9, 20, tzinfo=UTC)
    (post, delete) = discord_calls
    assert post[:2] == ("POST", CHANNEL)
    stamp = int(datetime(2026, 9, 9, 20, tzinfo=UTC).timestamp())
    assert post[2] == {
        "content": f"Scheduled by <@2>: <t:{stamp}:f> · Wk 1 · P2 (Alpha) vs P4 (Beta)"
        f" · #{series_id}"
    }
    assert delete[:2] == ("DELETE", f"{WEBHOOK}/messages/@original")


def test_schedule_refuses_a_stranger_and_a_bad_time_privately(
    client: Client, public_key: None, discord_calls: list, seeded: dict[str, Any]
) -> None:
    series_id = seeded["series_open_id"]
    body, headers = signed(
        command("schedule", user="1", series=series_id, when_utc="2026-09-09 20:00")
    )
    client.post("/discord/interactions", content=body, headers=headers)
    body, headers = signed(
        command("schedule", user="2", series=series_id, when_utc="tomorrow")
    )
    client.post("/discord/interactions", content=body, headers=headers)
    edit = f"{WEBHOOK}/messages/@original"
    assert discord_calls == [
        ("PATCH", edit, {"content": "not_authorized_for_this_series"}),
        ("PATCH", edit, {"content": "Give the time in UTC as YYYY-MM-DD HH:MM."}),
    ]
    with Session.begin() as session:
        series = session.get(Series, series_id)
        assert series and series.date_time is None


def test_register_commands_puts_the_guild_list(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "a-bot-token")
    monkeypatch.setenv("DISCORD_APPLICATION_ID", APP_ID)
    monkeypatch.setenv("DISCORD_GUILD_ID", "guild-1")
    seen: list[tuple[str, str, Any]] = []

    class Ok:
        ok = True
        status_code = 200

        def json(self) -> list[dict[str, str]]:
            return [{"name": c["name"]} for c in interactions.COMMANDS]

    def request(method: str, url: str, **kwargs: object) -> Ok:
        seen.append((method, url, kwargs.get("json")))
        return Ok()

    monkeypatch.setattr(requests, "request", request)
    assert interactions.register_commands() == [
        "upcoming",
        "leaderboard",
        "schedule",
        "score",
        "postlinks",
        "veto",
        "announce",
        "stats",
    ]
    assert seen == [
        (
            "PUT",
            f"{discord.API_URL}/applications/{APP_ID}/guilds/guild-1/commands",
            interactions.COMMANDS,
        )
    ]
