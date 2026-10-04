"""A player or a captain who changes a reported result through the report, or
takes it back, is named in a note the bot posts beside the result card, so a
past result never changes unseen. The first report posts the card alone, and
a captain's edit of the series and every admin write post no note.

The played series is P1 (Alpha) against P3 (Beta), 2-1; the open series is
P2 (Alpha) against P4 (Beta).
"""

from collections.abc import Callable
from typing import Any

import pytest
from httpx2 import Client
from sqlalchemy import select
from sqlmodel import col

from app.core.db import Session
from app.models.discord_post import DiscordPost
from app.models.settings import Settings
from app.services import discord, discord_posts, series_cards, series_games
from tests.test_discord_score import (  # noqa: F401  # attached is a fixture
    attached,
    scoring,
    send,
)
from tests.test_series_edit import seat

RESULTS = f"{discord.API_URL}/channels/results/messages"


@pytest.fixture
def results_channel(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("FRONTEND_URL", "https://gnl.test/")
    with Session.begin() as session:
        session.add(Settings(key="results_channel_id", value="results"))


def report(
    client: Client,
    series_id: int,
    headers: dict[str, str],
    p1: int,
    p2: int,
    **extra: object,
) -> None:
    resp = client.put(
        f"/player-series/{series_id}",
        headers=headers,
        json={
            "action": "score_updated",
            "player1_score": p1,
            "player2_score": p2,
            **extra,
        },
    )
    assert resp.status_code == 200, resp.text


def notes(calls: list[tuple[str, str, Any]]) -> list[list[str]]:
    """The lines of every note the bot posted, in order; a note carries its own colour."""
    return [
        call[2]["embeds"][0]["description"].splitlines()
        for call in calls
        if call[:2] == ("POST", RESULTS)
        and call[2]["embeds"][0]["color"] == series_cards.CHANGE_COLOR
    ]


def test_a_player_who_changes_his_result_is_named_beside_the_card(
    client: Client,
    discord_calls: list,
    seeded: dict[str, Any],
    member: Callable[..., dict[str, str]],
    results_channel: None,
) -> None:
    series_id = seeded["series_played_id"]
    report(client, series_id, member("1"), 2, 0)

    # The score changed, so the card is posted, then the note beside it
    assert [call[:2] for call in discord_calls] == [("POST", RESULTS)] * 2
    note = discord_calls[1][2]
    assert note["content"] == ""
    assert note["allowed_mentions"] == {"parse": []}
    lines = note["embeds"][0]["description"].splitlines()
    assert lines[0] == "## SL · Season 1"
    assert lines[1].startswith("Round 1")
    assert lines[3] == "### Team Alpha (Alpha) vs Team Beta (Beta)"
    assert lines[5:8] == [
        "**Result changed** by <@1> (player)",
        "Before ||P1 2-1 P3||",
        "Now ||P1 2-0 P3||",
    ]
    assert lines[9] == f"[Match page](<https://gnl.test/match/{seeded['match_id']}>)"
    with Session() as session:
        kinds = session.scalars(
            select(col(DiscordPost.kind)).where(
                col(DiscordPost.subject_id) == series_id
            )
        ).all()
    assert sorted(kinds) == [discord_posts.RESULT, discord_posts.RESULT_CHANGE]


def test_the_same_result_again_posts_nothing(
    client: Client,
    discord_calls: list,
    seeded: dict[str, Any],
    member: Callable[..., dict[str, str]],
    results_channel: None,
) -> None:
    report(client, seeded["series_played_id"], member("1"), 2, 1)
    assert discord_calls == []


def test_a_new_order_of_the_games_is_a_change(
    client: Client,
    discord_calls: list,
    seeded: dict[str, Any],
    member: Callable[..., dict[str, str]],
    results_channel: None,
) -> None:
    series_id = seeded["series_played_id"]
    series_games.record(
        series_id,
        [
            {"game_no": 1, "winner_side": "A"},
            {"game_no": 2, "winner_side": "B"},
            {"game_no": 3, "winner_side": "A"},
        ],
    )
    report(
        client,
        series_id,
        member("1"),
        2,
        1,
        games=[
            {"game_no": 1, "winner_side": "B"},
            {"game_no": 2, "winner_side": "A"},
            {"game_no": 3, "winner_side": "A"},
        ],
    )

    # The score stands, so the card is not edited; the note says what changed
    (note,) = notes(discord_calls)
    assert note[5:9] == [
        "**Result changed** by <@1> (player)",
        "Before ||P1 2-1 P3||",
        "Now ||P1 2-1 P3||",
        "The games changed",
    ]


def test_another_race_played_is_a_change(
    client: Client,
    discord_calls: list,
    seeded: dict[str, Any],
    member: Callable[..., dict[str, str]],
    results_channel: None,
) -> None:
    report(client, seeded["series_played_id"], member("1"), 2, 1, player1_off_race="OC")
    (note,) = notes(discord_calls)
    assert note[8] == "The races played changed"


def test_a_first_report_posts_the_card_alone(
    client: Client,
    discord_calls: list,
    seeded: dict[str, Any],
    member: Callable[..., dict[str, str]],
    results_channel: None,
) -> None:
    report(client, seeded["series_open_id"], member("2"), 2, 0)
    assert [call[:2] for call in discord_calls] == [("POST", RESULTS)]
    assert notes(discord_calls) == []


def test_a_result_taken_back_is_named_and_its_card_comes_down(
    client: Client,
    discord_calls: list,
    seeded: dict[str, Any],
    member: Callable[..., dict[str, str]],
    results_channel: None,
) -> None:
    series_id = seeded["series_open_id"]
    headers = member("2")
    report(client, series_id, headers, 2, 0)
    resp = client.delete(f"/series/{series_id}/result", headers=headers)
    assert resp.status_code == 200, resp.text

    assert [call[:2] for call in discord_calls] == [
        ("POST", RESULTS),
        ("DELETE", f"{RESULTS}/msg-1"),
        ("POST", RESULTS),
    ]
    (note,) = notes(discord_calls)
    assert note[5:7] == ["**Result cleared** by <@2> (player)", "Before ||P2 2-0 P4||"]


def test_a_captain_who_reports_is_named_as_the_captain(
    client: Client,
    discord_calls: list,
    seeded: dict[str, Any],
    member: Callable[..., dict[str, str]],
    results_channel: None,
) -> None:
    seat(seeded, "b", 3)
    report(client, seeded["series_played_id"], member("4"), 1, 2)
    (note,) = notes(discord_calls)
    assert note[5] == "**Result changed** by <@4> (captain)"


def test_a_captain_who_edits_the_series_posts_no_note(
    client: Client,
    discord_calls: list,
    seeded: dict[str, Any],
    member: Callable[..., dict[str, str]],
    results_channel: None,
) -> None:
    seat(seeded, "b", 3)
    resp = client.put(
        f"/series/{seeded['series_played_id']}",
        json={"player1_score": 1, "player2_score": 2},
        headers=member("4"),
    )
    assert resp.status_code == 200, resp.text
    assert [call[:2] for call in discord_calls] == [("POST", RESULTS)]
    assert notes(discord_calls) == []


def test_an_admin_who_reports_or_takes_back_posts_no_note(
    client: Client,
    discord_calls: list,
    seeded: dict[str, Any],
    auth_headers: dict[str, str],
    results_channel: None,
) -> None:
    series_id = seeded["series_played_id"]
    report(client, series_id, auth_headers, 2, 0)
    resp = client.delete(f"/series/{series_id}/result", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert [call[:2] for call in discord_calls] == [
        ("POST", RESULTS),
        ("DELETE", f"{RESULTS}/msg-1"),
    ]


def test_a_change_reported_from_discord_is_named(
    client: Client,
    public_key: None,
    discord_calls: list,
    seeded: dict[str, Any],
    attached: dict[str, bytes],  # noqa: F811  # the fixture of the score tests
    results_channel: None,
) -> None:
    send(client, scoring(attached, seeded["series_played_id"], 2, 0, user="1", games=2))
    (note,) = notes(discord_calls)
    assert note[5:8] == [
        "**Result changed** by <@1> (player)",
        "Before ||P1 2-1 P3||",
        "Now ||P1 2-0 P3||",
    ]


def test_without_the_setting_nothing_is_posted(
    client: Client,
    discord_calls: list,
    seeded: dict[str, Any],
    member: Callable[..., dict[str, str]],
) -> None:
    report(client, seeded["series_played_id"], member("1"), 2, 0)
    assert discord_calls == []
