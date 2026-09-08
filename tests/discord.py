"""Helpers for the Discord interaction tests: a signing key, payload builders and a
recorder for the calls the backend makes to Discord. The fixtures live in conftest."""

import json
import time
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

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


def command(name: str, user: str = "1", **options: int | bool | str) -> dict[str, Any]:
    return {
        "type": interactions.COMMAND,
        "application_id": APP_ID,
        "token": TOKEN,
        "channel_id": "chan-1",
        "member": {"user": {"id": user, "username": f"p{user}"}},
        "data": {
            "name": name,
            "options": [{"name": k, "value": v} for k, v in options.items()],
        },
    }


def autocomplete(name: str, user: str, typed: str) -> dict[str, Any]:
    return {
        "type": interactions.AUTOCOMPLETE,
        "application_id": APP_ID,
        "token": TOKEN,
        "member": {"user": {"id": user}},
        "data": {
            "name": name,
            "options": [{"name": "series", "value": typed, "focused": True}],
        },
    }


def record(monkeypatch: pytest.MonkeyPatch, status: int) -> list[tuple[str, str, Any]]:
    calls: list[tuple[str, str, Any]] = []

    class Answer:
        ok = status < 400
        status_code = status

        def json(self) -> dict[str, str]:
            # Every channel post gets its own message id: msg-1, msg-2, ...
            return {"id": f"msg-{sum(call[0] == 'POST' for call in calls)}"}

    def request(method: str, url: str, **kwargs: object) -> Answer:
        calls.append((method, url, kwargs.get("json")))
        return Answer()

    monkeypatch.setattr(discord.requests, "request", request)
    return calls


class Clock:
    """The clock the bot post pacing reads, and the sleeps it asked for."""

    def __init__(self) -> None:
        self.now = datetime.now(UTC)
        self.sleeps: list[float] = []

    def read(self) -> datetime:
        # time moves between two reads, as it does on a real clock
        self.now += timedelta(microseconds=1)
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(round(seconds, 3))
        self.now += timedelta(seconds=seconds)
