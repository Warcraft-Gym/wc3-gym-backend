"""A cup's announcements in Discord, and the Home switch that takes the role.

A cup announces itself once it takes signups, calls its players to check in an
hour before it starts, says when it is drawn and when a round is drawn, and
posts its top three when it closes. Every message pings the announcement role,
and each goes out once.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx2 import Client
from sqlalchemy import select
from sqlmodel import col

from app.core.db import Session
from app.models.cup_rounds import CupLeg
from app.models.enums import EventKind, SchedulingMode, StageFormat
from app.models.season import Season
from app.models.settings import Settings
from app.services import cup_announcements, discord
from tests.discord import record
from tests.test_awards import play_out
from tests.test_cup_divisions import make_cup
from tests.test_cup_rounds import LEGS
from tests.test_cup_swiss import draw_round, play_round
from tests.test_event_organizers import CUP, Headers, Member
from tests.test_stage_engine import cup, generate, team_cup

ANNOUNCE = f"{discord.API_URL}/channels/announce/messages"
ROLE = "role-9"
JOB = "/jobs/cast-reminders"
SECRET = {"Authorization": "Bearer cast-secret"}


@pytest.fixture
def announcements() -> None:
    with Session.begin() as session:
        session.add(Settings(key="announcement_channel_id", value="announce"))
        session.add(Settings(key="announcement_role_id", value=ROLE))


@pytest.fixture
def cron(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("CLOUDFLARE_CRON_SECRET", "cast-secret")


def posts(calls: list[tuple[str, str, Any]]) -> list[str]:
    """The text of every announcement posted, in order."""
    return [
        body["content"]
        for method, url, body in calls
        if (method, url) == ("POST", ANNOUNCE)
    ]


def starts_in(event_id: int, minutes: float) -> None:
    with Session.begin() as session:
        cup_row = session.get(Season, event_id)
        assert cup_row is not None
        cup_row.starts_at = datetime.now(UTC) + timedelta(minutes=minutes)


def test_a_cup_taking_signups_is_announced_once_with_the_role(
    client: Client, auth_headers: Headers, discord_calls: list, announcements: None
) -> None:
    made = client.post("/events", json=CUP, headers=auth_headers)
    assert made.status_code == 201, made.text
    event = made.json()["id"]
    [text] = posts(discord_calls)
    assert text == f"<@&{ROLE}> A new cup takes signups: **Friday Night Cup**"
    body = discord_calls[0][2]
    assert body["allowed_mentions"] == {"roles": [ROLE]}
    assert "## Friday Night Cup" in body["embeds"][0]["description"]

    # another edit of the open cup posts nothing again
    edited = client.put(
        f"/events/{event}", json={"name": "Friday Cup"}, headers=auth_headers
    )
    assert edited.status_code == 200, edited.text
    assert len(posts(discord_calls)) == 1


def test_a_draft_is_announced_when_it_is_published(
    client: Client, auth_headers: Headers, discord_calls: list, announcements: None
) -> None:
    made = client.post("/events", json=CUP | {"published": False}, headers=auth_headers)
    assert made.status_code == 201, made.text
    assert posts(discord_calls) == []
    event = made.json()["id"]
    published = client.put(
        f"/events/{event}", json={"published": True}, headers=auth_headers
    )
    assert published.status_code == 200, published.text
    assert len(posts(discord_calls)) == 1


def test_nothing_is_announced_without_the_channel_or_for_another_kind(
    client: Client, auth_headers: Headers, discord_calls: list
) -> None:
    made = client.post("/events", json=CUP, headers=auth_headers)
    assert made.status_code == 201, made.text
    assert discord_calls == []
    with Session.begin() as session:
        session.add(Settings(key="announcement_channel_id", value="announce"))
        listed = Season(
            name="List",
            kind=EventKind.signup,
            series_per_round=1,
            published=True,
            signups_open=True,
        )
        session.add(listed)
        session.flush()
        listed_id = listed.id
    assert listed_id is not None
    assert cup_announcements.announce_open(listed_id) is False
    assert discord_calls == []


def test_a_cup_starting_within_the_hour_is_called_to_check_in_once(
    client: Client,
    auth_headers: Headers,
    discord_calls: list,
    announcements: None,
    cron: None,
) -> None:
    soon = client.post(
        "/events", json=CUP | {"published": False}, headers=auth_headers
    ).json()["id"]
    later = client.post(
        "/events",
        json=CUP | {"published": False, "name": "Later"},
        headers=auth_headers,
    ).json()["id"]
    started = client.post(
        "/events",
        json=CUP | {"published": False, "name": "Started"},
        headers=auth_headers,
    ).json()["id"]
    with Session.begin() as session:
        for event_id in (soon, later, started):
            row = session.get(Season, event_id)
            assert row is not None
            row.published = True
            row.checkin_enabled = True
    starts_in(soon, 30)
    starts_in(later, 120)
    starts_in(started, -5)

    first = client.get(JOB, headers=SECRET)
    assert first.status_code == 200, first.text
    assert first.json()["cup_reminders"] == 1
    [text] = posts(discord_calls)
    assert text.startswith(f"<@&{ROLE}> **Friday Night Cup** starts <t:")
    assert text.endswith("Check in now on the cup page.")
    again = client.get(JOB, headers=SECRET)
    assert again.json()["cup_reminders"] == 0


def test_a_cup_over_rounds_calls_each_round_to_check_in(
    client: Client,
    auth_headers: Headers,
    discord_calls: list,
    announcements: None,
    cron: None,
) -> None:
    made = make_cup(client, auth_headers, legs=LEGS, published=False)
    with Session.begin() as session:
        row = session.get(Season, made["id"])
        assert row is not None
        row.published = True
        legs = list(
            session.scalars(
                select(CupLeg)
                .where(col(CupLeg.event_id) == made["id"])
                .order_by(col(CupLeg.number))
            )
        )
        # the cup and its first round start together; only the round is called
        row.starts_at = legs[0].starts_at = datetime.now(UTC) + timedelta(minutes=20)
    answer = client.get(JOB, headers=SECRET)
    assert answer.json()["cup_reminders"] == 1
    [text] = posts(discord_calls)
    assert text.startswith(f"<@&{ROLE}> Round 1 of **Friday Night Cup** starts <t:")


def test_the_draw_each_round_and_the_playoff_are_announced_then_the_podium(
    client: Client, auth_headers: Headers, discord_calls: list, announcements: None
) -> None:
    event, (swiss, playoff) = cup(
        8,
        StageFormat.swiss,
        stages=2,
        swiss_rounds=3,
        best_of=1,
        scheduling_mode=SchedulingMode.immediate,
        auto_advance=True,
        advance_count=4,
    )
    assert draw_round(client, auth_headers, event, swiss).status_code == 200
    for _ in range(3):
        play_round(client, auth_headers, swiss)
    while play_round(client, auth_headers, playoff, wins=2):
        pass
    finished = client.post(f"/events/{event}/finish", headers=auth_headers)
    assert finished.status_code == 200, finished.text

    texts = [text.removeprefix(f"<@&{ROLE}> ") for text in posts(discord_calls)]
    assert texts == [
        "The draw of **Autumn Cup** is out.",
        "Round 2 of **Autumn Cup** is drawn.",
        "Round 3 of **Autumn Cup** is drawn.",
        "Stage 2 of **Autumn Cup** is drawn.",
        "**Autumn Cup** is over. The podium:",
    ]
    podium = discord_calls[-1][2]["embeds"][0]["description"].splitlines()
    assert podium[0] == "## 🏆 Autumn Cup"
    assert [line[:1] for line in podium[1:]] == ["🥇", "🥈", "🥉"]

    # a second close edits the card and pings nobody again
    client.post(f"/events/{event}/reopen", headers=auth_headers)
    again = client.post(f"/events/{event}/finish", headers=auth_headers)
    assert again.status_code == 200, again.text
    assert len(posts(discord_calls)) == 5
    assert discord_calls[-1][0] == "PATCH"


def test_a_redraw_and_a_refused_draw_post_nothing(
    client: Client, auth_headers: Headers, discord_calls: list, announcements: None
) -> None:
    event, (stage,) = cup(4)
    generate(client, auth_headers, event, stage)
    assert len(posts(discord_calls)) == 1
    undone = client.delete(
        f"/events/{event}/stages/{stage}/series", headers=auth_headers
    )
    assert undone.status_code in (200, 204), undone.text
    generate(client, auth_headers, event, stage)
    refused = client.post(
        f"/events/{event}/stages/{stage}/generate", headers=auth_headers
    )
    assert refused.status_code == 400
    assert len(posts(discord_calls)) == 1


def test_a_team_cups_podium_names_each_team_with_its_players(
    client: Client,
    auth_headers: Headers,
    member: Member,
    discord_calls: list,
    announcements: None,
) -> None:
    event, stage, _, _ = team_cup(client, auth_headers, member)
    generate(client, auth_headers, event, stage)
    play_out(client, auth_headers, stage)
    assert (
        client.post(f"/events/{event}/finish", headers=auth_headers).status_code == 200
    )
    podium = discord_calls[-1][2]["embeds"][0]["description"].splitlines()
    assert podium[1].startswith("🥇 T")
    assert "(E" in podium[1]


def test_the_home_switch_takes_and_leaves_the_role(
    client: Client, member: Member, discord_calls: list, announcements: None
) -> None:
    headers = member("777")
    assert client.get("/me/announcements", headers=headers).json() == {
        "available": True,
        "subscribed": False,
    }
    taken = client.put("/me/announcements", json={"subscribed": True}, headers=headers)
    assert taken.status_code == 200, taken.text
    assert taken.json() == {"available": True, "subscribed": True}
    assert discord_calls[-1][0] == "PUT"
    assert discord_calls[-1][1].endswith(f"/members/777/roles/{ROLE}")
    assert client.get("/me/announcements", headers=headers).json()["subscribed"] is True
    left = client.put("/me/announcements", json={"subscribed": False}, headers=headers)
    assert left.json()["subscribed"] is False
    assert discord_calls[-1][0] == "DELETE"


def test_the_switch_says_when_discord_refuses_or_nothing_is_set_up(
    client: Client,
    member: Member,
    auth_headers: Headers,
    bot_token: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    headers = member("778")
    assert client.get("/me/announcements", headers=headers).json()["available"] is False
    assert (
        client.put(
            "/me/announcements", json={"subscribed": True}, headers=headers
        ).status_code
        == 400
    )
    with Session.begin() as session:
        session.add(Settings(key="announcement_channel_id", value="announce"))
        session.add(Settings(key="announcement_role_id", value=ROLE))
    record(monkeypatch, 403)
    refused = client.put(
        "/me/announcements", json={"subscribed": True}, headers=headers
    )
    assert refused.status_code == 502, refused.text
    assert (
        client.get("/me/announcements", headers=headers).json()["subscribed"] is False
    )
    # the admin token holds no Discord account to give the role
    assert (
        client.get("/me/announcements", headers=auth_headers).json()["available"]
        is False
    )
