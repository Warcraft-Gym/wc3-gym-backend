"""/postlinks: an admin posts the site's link buttons, in this channel or another."""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx2 import Client

from app.services import discord
from tests.discord import CHANNEL, WEBHOOK, command, signed
from tests.test_fantasy_locks import schedule, score

ADMIN = "220202568490418179"
# Round 1 of the seeded season starts on 5 Jan 2026
ROUND_1 = "<t:1767571200:D>"
SIGN_IN = "Sign in with your Discord account to use these."
SITE = "https://warcraftgym.com"


@pytest.fixture
def admin(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ADMIN_DISCORD_IDS", ADMIN)
    monkeypatch.setenv("FRONTEND_URL", f"{SITE}/")


def post(client: Client, **options: str) -> None:
    body, headers = signed(command("postlinks", user=ADMIN, **options))
    assert client.post(
        "/discord/interactions", content=body, headers=headers
    ).json() == {"ok": True}


def test_admin_posts_the_three_link_buttons(
    client: Client, public_key: None, discord_calls: list, admin: None
) -> None:
    post(client)
    (posted, delete) = discord_calls
    assert posted[:2] == ("POST", CHANNEL)
    assert posted[2]["content"] == f"**Warcraft Gym**\n{SIGN_IN}"
    assert posted[2]["components"][0]["type"] == 1
    assert [
        (button["label"], button["url"], button["type"], button["style"])
        for button in posted[2]["components"][0]["components"]
    ] == [
        ("Sign up", f"{SITE}/signup", 2, 5),
        ("Player dashboard", f"{SITE}/player-dashboard", 2, 5),
        ("Fantasy", f"{SITE}/fantasy-registration", 2, 5),
    ]
    assert delete[:2] == ("DELETE", f"{WEBHOOK}/messages/@original")


def test_a_member_is_refused_privately(
    client: Client,
    public_key: None,
    discord_calls: list,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ADMIN_DISCORD_IDS", ADMIN)
    monkeypatch.setenv("FRONTEND_URL", SITE)
    body, headers = signed(command("postlinks", user="1"))
    client.post("/discord/interactions", content=body, headers=headers)
    assert discord_calls == [
        ("PATCH", f"{WEBHOOK}/messages/@original", {"content": "Admins only."})
    ]


def test_no_frontend_url_answers_privately(
    client: Client,
    public_key: None,
    discord_calls: list,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ADMIN_DISCORD_IDS", ADMIN)
    monkeypatch.delenv("FRONTEND_URL", raising=False)
    post(client)
    assert discord_calls == [
        (
            "PATCH",
            f"{WEBHOOK}/messages/@original",
            {"content": "FRONTEND_URL is not set."},
        )
    ]


def test_the_channel_option_posts_there(
    client: Client, public_key: None, discord_calls: list, admin: None
) -> None:
    post(client, channel="chan-2")
    (posted, patch) = discord_calls
    assert posted[:2] == ("POST", f"{discord.API_URL}/channels/chan-2/messages")
    assert patch == (
        "PATCH",
        f"{WEBHOOK}/messages/@original",
        {"content": "Posted in <#chan-2>."},
    )


def test_an_open_season_card_says_signups_are_open(
    client: Client,
    seeded: dict[str, Any],
    public_key: None,
    discord_calls: list,
    admin: None,
) -> None:
    score(seeded["series_played_id"], None, None)
    schedule(seeded["series_played_id"], datetime.now(UTC) + timedelta(days=1))
    post(client)
    assert discord_calls[0][2]["content"] == (
        f"**Season 1** · Round 1 {ROUND_1}\nSignups are open. {SIGN_IN}"
    )


def test_a_commenced_season_card_says_signups_are_closed(
    client: Client,
    seeded: dict[str, Any],
    public_key: None,
    discord_calls: list,
    admin: None,
) -> None:
    post(client)
    assert discord_calls[0][2]["content"] == (
        f"**Season 1** · Round 1 {ROUND_1}\nSignups are closed. {SIGN_IN}"
    )
