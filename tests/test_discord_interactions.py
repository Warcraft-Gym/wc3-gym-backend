"""The interactions route: Discord's signature is the auth, and a command
answers through the interaction token, never through the route's own body."""

import json
import time
from datetime import timedelta
from typing import Any

import pytest
import requests
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
from httpx2 import Client

from app.core.db import Session
from app.models.series import Series
from app.models.types import utcnow
from app.services import discord, interactions

KEY = Ed25519PrivateKey.generate()
PUBLIC_KEY = (
    KEY.public_key()
    .public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    .hex()
)
APP_ID, TOKEN = "app-1", "interaction-token"
WEBHOOK = f"{discord.API_URL}/webhooks/{APP_ID}/{TOKEN}"
CHANNEL = f"{discord.API_URL}/channels/chan-1/messages"


def signed(
    payload: dict[str, Any], key: Ed25519PrivateKey = KEY
) -> tuple[bytes, dict[str, str]]:
    body = json.dumps(payload).encode()
    stamp = str(int(time.time()))
    return body, {
        "Content-Type": "application/json",
        "X-Signature-Ed25519": key.sign(stamp.encode() + body).hex(),
        "X-Signature-Timestamp": stamp,
    }


def command(name: str, **options: int | bool) -> dict[str, Any]:
    return {
        "type": interactions.COMMAND,
        "application_id": APP_ID,
        "token": TOKEN,
        "channel_id": "chan-1",
        "member": {"user": {"id": "1"}},
        "data": {
            "name": name,
            "options": [{"name": k, "value": v} for k, v in options.items()],
        },
    }


@pytest.fixture
def public_key(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DISCORD_PUBLIC_KEY", PUBLIC_KEY)


@pytest.fixture
def bot_token(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "a-bot-token")


@pytest.fixture
def discord_calls(
    monkeypatch: pytest.MonkeyPatch, bot_token: None
) -> list[tuple[str, str, Any]]:
    """Record every call to Discord and answer 200."""
    return _record(monkeypatch, 200)


def _record(monkeypatch: pytest.MonkeyPatch, status: int) -> list[tuple[str, str, Any]]:
    calls: list[tuple[str, str, Any]] = []

    class Answer:
        ok = status < 400
        status_code = status

    def request(method: str, url: str, **kwargs: object) -> Answer:
        calls.append((method, url, kwargs.get("json")))
        return Answer()

    monkeypatch.setattr(discord.requests, "request", request)
    return calls


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


def test_upcoming_posts_the_window_publicly(
    client: Client, public_key: None, discord_calls: list, seeded: dict[str, Any]
) -> None:
    soon = utcnow() + timedelta(days=2)
    with Session.begin() as session:
        series = session.get(Series, seeded["series_open_id"])
        assert series
        series.date_time = soon
        series.caster = "gnlcaster"
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


def test_upcoming_stays_private_without_a_bot_token_or_when_refused(
    client: Client, public_key: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
    calls = _record(monkeypatch, 200)
    body, headers = signed(command("upcoming"))
    client.post("/discord/interactions", content=body, headers=headers)
    assert [(c[0], c[1]) for c in calls] == [("PATCH", f"{WEBHOOK}/messages/@original")]
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "a-bot-token")
    calls = _record(monkeypatch, 403)
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


def test_autocomplete_answers_no_choices_yet(client: Client, public_key: None) -> None:
    body, headers = signed(
        {
            "type": 4,
            "application_id": APP_ID,
            "token": TOKEN,
            "data": {"name": "upcoming"},
        }
    )
    resp = client.post("/discord/interactions", content=body, headers=headers)
    assert resp.json() == {"type": 8, "data": {"choices": []}}


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
    assert interactions.register_commands() == ["upcoming"]
    assert seen == [
        (
            "PUT",
            f"{discord.API_URL}/applications/{APP_ID}/guilds/guild-1/commands",
            interactions.COMMANDS,
        )
    ]
