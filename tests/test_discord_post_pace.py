"""The bot's cards are edited one a second per channel, a burst of writes edits
each card once with the latest state, and a rate limit answer is waited out."""

from typing import Any

import pytest

from app.services import discord, discord_posts
from tests.discord import Clock

CHANNEL = f"{discord.API_URL}/channels/chan/messages"


def edits(calls: list[tuple[str, str, Any]]) -> list[str]:
    return [call[1].removeprefix(f"{CHANNEL}/") for call in calls if call[0] == "PATCH"]


@pytest.fixture
def two_cards(seeded: dict[str, Any], clock: Clock) -> int:
    """A veto card and an announce card of the open series, posted in one
    channel a while ago."""
    series_id = seeded["series_open_id"]
    discord_posts.remember("veto", series_id, "chan", "m1")
    discord_posts.remember("announce", series_id, "chan", "m2")
    clock.sleep(60)
    clock.sleeps.clear()
    return series_id


def test_two_cards_in_one_channel_are_edited_a_second_apart(
    discord_calls: list, two_cards: int, clock: Clock
) -> None:
    discord_posts.refresh_series(two_cards)
    assert edits(discord_calls) == ["m1", "m2"]
    assert clock.sleeps == [1.0]

    discord_calls.clear()
    discord_posts.refresh_series(two_cards)
    assert edits(discord_calls) == ["m1", "m2"]
    assert clock.sleeps == [1.0, 1.0, 1.0]


def test_a_burst_of_changes_edits_each_card_once(
    discord_calls: list, two_cards: int, clock: Clock
) -> None:
    for _ in range(8):
        discord_posts.mark_series(two_cards)
    discord_posts.flush_series(two_cards)
    assert edits(discord_calls) == ["m1", "m2"]

    # nothing changed since: the flush of a slower task edits nothing
    discord_calls.clear()
    discord_posts.flush_series(two_cards)
    assert edits(discord_calls) == []
    assert clock.sleeps == [1.0]


def test_a_change_during_the_edit_is_carried_by_the_next_task(
    discord_calls: list, two_cards: int
) -> None:
    discord_posts.refresh_series(two_cards, ("veto",))
    discord_posts.mark_series(two_cards, ("veto",))  # a step landed while m1 was edited
    discord_calls.clear()
    discord_posts.flush_series(two_cards, ("veto",))
    assert edits(discord_calls) == ["m1"]


def test_a_new_post_waits_for_the_channels_second(
    discord_calls: list, seeded: dict[str, Any], clock: Clock
) -> None:
    from app.core.db import Session
    from app.models.settings import Settings

    with Session.begin() as session:
        session.add(Settings(key="results_channel_id", value="chan"))
    discord_posts.remember("veto", seeded["series_open_id"], "chan", "m1")
    discord_posts.post_result(seeded["series_played_id"])
    assert [call[0] for call in discord_calls] == ["POST"]
    assert clock.sleeps == [1.0]


def test_a_rate_limited_channel_call_waits_and_tries_once_more(
    monkeypatch: pytest.MonkeyPatch, bot_token: None
) -> None:
    answers = [(429, {"retry_after": 0.7}), (200, {"id": "m9"})]
    calls: list[str] = []
    sleeps: list[float] = []

    class Answer:
        def __init__(self, status: int, body: dict[str, Any]) -> None:
            self.status_code = status
            self.ok = status < 400
            self.body = body

        def json(self) -> dict[str, Any]:
            return self.body

    def request(method: str, url: str, **kwargs: object) -> Answer:
        calls.append(method)
        return Answer(*answers.pop(0))

    monkeypatch.setattr(discord.requests, "request", request)
    monkeypatch.setattr(discord, "sleep", sleeps.append)
    assert discord.post_to_channel("chan", {"content": "hi"}) == "m9"
    assert calls == ["POST", "POST"]
    assert sleeps == [0.7]
