"""The production build's Discord step: the commands and the emojis, and never a failed build."""

import json
import re
from pathlib import Path
from typing import Any

import pytest
import requests

from api import discord_setup
from app.services import discord, interactions

API = "https://discord.com/api/v10"


@pytest.fixture
def discord_values(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """The three production values, and an emoji folder of two images."""
    monkeypatch.setenv("DISCORD_APPLICATION_ID", "app")
    monkeypatch.setenv("DISCORD_GUILD_ID", "guild")
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "a-bot-token")
    (tmp_path / "HU.png").write_bytes(b"hu")
    (tmp_path / "OC.png").write_bytes(b"oc")
    monkeypatch.setattr(discord_setup, "EMOJIS", tmp_path)
    return tmp_path


def test_without_the_discord_values_the_step_does_nothing(
    monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    for name in discord_setup.NEEDED:
        monkeypatch.delenv(name, raising=False)
    monkeypatch.setenv("DISCORD_APPLICATION_ID", "app")
    calls: list[str] = []
    monkeypatch.setattr(
        discord._session, "request", lambda *args, **kwargs: calls.append("call")
    )

    assert discord_setup.main() == 0
    assert calls == []
    out = capsys.readouterr().out
    assert "skipped: DISCORD_GUILD_ID, DISCORD_BOT_TOKEN not set" in out


def test_the_step_registers_the_commands_and_uploads_the_missing_emojis(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    discord_values: Path,
) -> None:
    calls: list[tuple[str, str]] = []

    class Answer:
        ok = True
        status_code = 200

        def __init__(self, method: str, url: str) -> None:
            self.method, self.url = method, url

        def json(self) -> list[dict[str, str]] | dict[str, Any]:
            if self.method == "PUT":
                return [{"name": c["name"]} for c in interactions.COMMANDS]
            # HU is on the application already
            return {"items": [{"name": "HU", "id": "11"}]}

    def request(method: str, url: str, **kwargs: object) -> Answer:
        calls.append((method, url))
        return Answer(method, url)

    monkeypatch.setattr(discord._session, "request", request)

    assert discord_setup.main() == 0
    assert calls == [
        ("PUT", f"{API}/applications/app/guilds/guild/commands"),
        ("GET", f"{API}/applications/app/emojis"),
        ("POST", f"{API}/applications/app/emojis"),
    ]
    out = capsys.readouterr().out
    assert "Discord commands registered: upcoming, leaderboard" in out
    assert "Discord emojis uploaded: OC" in out


def test_a_refusing_discord_never_fails_the_build(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    discord_values: Path,
) -> None:
    class Refused:
        ok = False
        status_code = 403
        text = "Missing Access"

        def json(self) -> dict[str, Any]:
            return {"items": []}

    monkeypatch.setattr(discord._session, "request", lambda *args, **kwargs: Refused())

    assert discord_setup.main() == 0
    out = capsys.readouterr().out
    assert "Warning: the Discord commands were not registered: 502" in out
    assert "Warning: the Discord emojis were not uploaded: 403" in out
    # the reason never carries the token
    assert "a-bot-token" not in out


def test_an_unreachable_discord_never_fails_the_build(
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
    discord_values: Path,
) -> None:
    def unreachable(*args: object, **kwargs: object) -> None:
        raise requests.ConnectionError("no route to discord.com")

    monkeypatch.setattr(discord._session, "request", unreachable)

    assert discord_setup.main() == 0
    out = capsys.readouterr().out
    assert "commands were not registered: ConnectionError" in out
    # an unreadable emoji list reads as empty, so the upload is what fails
    assert "emojis were not uploaded: ConnectionError" in out


def test_only_production_sets_discord_up_after_the_migrations() -> None:
    build = json.loads(Path("vercel.json").read_text())["buildCommand"]
    branches = dict(re.findall(r"(\w+)\) (.*?) ;;", build))
    assert branches["production"] == (
        "uv run --frozen alembic upgrade head"
        " && uv run --frozen python -m api.discord_setup"
    )
    assert "discord_setup" not in branches["preview"]
