"""The profile links and the Discord avatar.

A player enters a Twitch or YouTube channel, never a video link. The avatar
comes from the Discord login, and the profile keeps the last one it saw.
"""

from typing import Any

import pytest
from pydantic import ValidationError

from app.models.user import ProfileUpdate
from app.services import casts
from app.services.users import UserService
from tests.conftest import Client
from tests.test_discord_auth import SESSION, stub_clerk

AVATAR = "https://cdn.discordapp.com/avatars/1/abc.png"


@pytest.fixture
def player_one(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """The Clerk session of the seeded player with Discord id 1."""
    monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
    monkeypatch.setattr(UserService, "validate_battle_tag", lambda self, tag: True)
    monkeypatch.setattr(UserService, "update_w3c_stats_by_id", lambda self, uid: None)
    stub_clerk(monkeypatch, account={"id": "1", "username": "p1", "avatar": "abc"})
    return SESSION


@pytest.mark.parametrize(
    "value,expected",
    [
        ("gnlcaster", "https://twitch.tv/gnlcaster"),
        ("twitch.tv/gnlcaster", "https://twitch.tv/gnlcaster"),
        ("https://www.twitch.tv/gnlcaster", "https://www.twitch.tv/gnlcaster"),
        ("  ", None),
        ("", None),
        (None, None),
    ],
)
def test_a_twitch_channel_is_taken(value: str | None, expected: str | None) -> None:
    assert ProfileUpdate(twitch_url=value).twitch_url == expected


@pytest.mark.parametrize(
    "value,expected",
    [
        ("@name", "https://youtube.com/@name"),
        ("youtube.com/@name", "https://youtube.com/@name"),
        ("https://m.youtube.com/c/name", "https://m.youtube.com/c/name"),
        ("", None),
    ],
)
def test_a_youtube_channel_is_taken(value: str, expected: str | None) -> None:
    assert ProfileUpdate(youtube_url=value).youtube_url == expected


@pytest.mark.parametrize(
    "value", ["twitch.tv/videos/1234", "youtube.com/@name", "example.com/gnl"]
)
def test_a_video_or_another_host_is_no_twitch_channel(value: str) -> None:
    with pytest.raises(ValidationError, match="A Twitch channel link is needed"):
        ProfileUpdate(twitch_url=value)


@pytest.mark.parametrize(
    "value",
    [
        "youtube.com/watch?v=abc",
        "https://youtube.com/live/abc",
        "youtu.be/abc",
        "twitch.tv/gnlcaster",
    ],
)
def test_a_video_or_another_host_is_no_youtube_channel(value: str) -> None:
    with pytest.raises(ValidationError, match="A YouTube channel link"):
        ProfileUpdate(youtube_url=value)


def test_a_member_saves_their_channels(
    client: Client, seeded: dict[str, Any], player_one: dict[str, str]
) -> None:
    resp = client.put(
        "/user-info",
        json={"twitch_url": "gnlcaster", "youtube_url": "@gnlcaster"},
        headers=player_one,
    )
    assert resp.status_code == 200, resp.text
    user = resp.json()["user"]
    assert user["twitch_url"] == "https://twitch.tv/gnlcaster"
    assert user["youtube_url"] == "https://youtube.com/@gnlcaster"

    read = client.get(f"/users/{user['id']}").json()
    assert read["twitch_url"] == "https://twitch.tv/gnlcaster"


def test_a_video_link_is_refused_on_the_profile(
    client: Client, seeded: dict[str, Any], player_one: dict[str, str]
) -> None:
    resp = client.put(
        "/user-info", json={"twitch_url": "twitch.tv/videos/7"}, headers=player_one
    )
    assert resp.status_code == 422, resp.text
    assert "not a video" in resp.text


def test_the_login_writes_the_avatar_once(
    client: Client,
    seeded: dict[str, Any],
    player_one: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    written: list[str | None] = []
    set_avatar = UserService.set_avatar

    def spy(self: UserService, user_id: int, avatar_url: str | None) -> None:
        written.append(avatar_url)
        set_avatar(self, user_id, avatar_url)

    monkeypatch.setattr(UserService, "set_avatar", spy)

    answer = client.get("/me", headers=player_one).json()
    assert answer["avatar"] == AVATAR
    assert answer["user"]["avatar_url"] == AVATAR
    assert written == [AVATAR]

    # the second login sees the same avatar and writes nothing
    assert client.get("/me", headers=player_one).json()["user"]["avatar_url"] == AVATAR
    assert written == [AVATAR]


def test_the_profile_channel_pre_fills_the_next_claim(
    client: Client, seeded: dict[str, Any], player_one: dict[str, str]
) -> None:
    user_id = seeded["player_ids"][0]
    assert casts.last_channel(user_id) is None

    client.post(
        f"/series/{seeded['series_open_id']}/casts",
        json={"channel_url": "twitch.tv/fromtheclaim"},
        headers=player_one,
    )
    assert casts.last_channel(user_id) == "https://twitch.tv/fromtheclaim"

    resp = client.put(
        "/user-info", json={"youtube_url": "@gnlcaster"}, headers=player_one
    )
    assert resp.status_code == 200, resp.text
    assert casts.last_channel(user_id) == "https://youtube.com/@gnlcaster"

    # twitch comes first when the profile carries both
    client.put("/user-info", json={"twitch_url": "gnlcaster"}, headers=player_one)
    assert casts.last_channel(user_id) == "https://twitch.tv/gnlcaster"
