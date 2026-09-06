"""/postlinks: an admin posts the site's link buttons, in this channel or another."""

import pytest
from httpx2 import Client

from app.services import discord
from tests.discord import CHANNEL, WEBHOOK, command, signed

ADMIN = "220202568490418179"
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
    assert posted[2]["content"].startswith("**Warcraft Gym**")
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
