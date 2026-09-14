"""The event card: what it says, the post it stores and what its buttons write.

An admin posts one card per channel and a repost edits it. Each press writes
through the entrant service, so the card, the home page and the event page
agree on what the member may do. Nothing here posts to Discord for real.
"""

from datetime import timedelta
from typing import Any

import pytest
from httpx2 import Client

from app.core.db import Session
from app.models.base import ident
from app.models.discord_post import DiscordPost
from app.models.enums import EventKind, Race, StageFormat
from app.models.event_entrant import EventEntrant
from app.models.event_stage import EventStage
from app.models.league import League
from app.models.season import Season
from app.services import event_cards, series_cards
from app.services.events import EventService
from tests.discord import APP_ID, TOKEN, WEBHOOK, signed
from tests.test_events import TODAY, add_event, add_round, set_fields

SITE = "https://gnl.test"
CHANNEL = "chan-1"


def in_gnl(event_id: int) -> None:
    with Session.begin() as session:
        league = League(name="Grand National League", short_name="GNL")
        session.add(league)
        session.flush()
        event = session.get(Season, event_id)
        assert event is not None
        event.league_id = league.id


def add_stage(event_id: int, **fields: Any) -> None:  # noqa: ANN401
    with Session.begin() as session:
        session.add(EventStage(event_id=event_id, position=1, **fields))


def enter(event_id: int, user_id: int) -> int:
    with Session.begin() as session:
        row = EventEntrant(event_id=event_id, user_id=user_id, race=Race.HU)
        session.add(row)
        session.flush()
        return ident(row)


def press(prefix: str, event_id: int, user: str = "1") -> dict[str, Any]:
    from app.services import interactions

    return {
        "type": interactions.COMPONENT,
        "application_id": APP_ID,
        "token": TOKEN,
        "channel_id": CHANNEL,
        "member": {"user": {"id": user, "username": f"p{user}"}},
        "data": {"custom_id": f"{prefix}:{event_id}", "component_type": 2},
    }


def send(client: Client, payload: dict[str, Any]) -> None:
    body, headers = signed(payload)
    assert client.post(
        "/discord/interactions", content=body, headers=headers
    ).json() == {"ok": True}


def reply(calls: list[tuple[str, str, Any]]) -> str:
    """The private answer the press edited into the deferred reply."""
    assert calls[-1][:2] == ("PATCH", f"{WEBHOOK}/messages/@original")
    return str(calls[-1][2]["content"])


@pytest.fixture
def cup(seeded: dict[str, Any]) -> int:
    """A published cup in the GNL league, open for signups, with one stage."""
    event = add_event(
        kind=EventKind.cup,
        start_date=TODAY + timedelta(days=7),
        end_date=TODAY + timedelta(days=8),
        entrant_cap=8,
        page_url="https://rules.test/autumn",
    )
    in_gnl(event)
    add_stage(event, format=StageFormat.single_elimination, best_of=3, name="Playoffs")
    return event


def test_the_card_names_the_event_its_format_and_how_to_enter(
    cup: int, seeded: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The league rides on the name, the stage says how it plays and the
    signup policy is a sentence. One entrant reads singular."""
    monkeypatch.setenv("FRONTEND_URL", SITE)
    enter(cup, seeded["player_ids"][0])

    card = event_cards.event_card(EventService().get(cup))

    assert card["embeds"][0]["description"].splitlines() == [
        "## GNL · Autumn Cup",
        (
            f"{series_cards.day(TODAY + timedelta(days=7))} to "
            f"{series_cards.day(TODAY + timedelta(days=8))}"
        ),
        "Playoffs · single elimination · best of 3",
        "1 entrant of 8",
        "Sign up with the Discord account linked to your profile.",
        f"[Event page](<{SITE}/events/{cup}>)",
        "[Rules](<https://rules.test/autumn>)",
    ]
    # The cup starts in seven days, so its three day check-in window is shut
    buttons = card["components"][0]["components"]
    assert [(b["label"], b["custom_id"], b["disabled"]) for b in buttons] == [
        ("Sign up", f"event_signup:{cup}", False),
        ("Check in", f"event_checkin:{cup}", True),
    ]

    set_fields(cup, start_date=TODAY + timedelta(days=1))
    open_card = event_cards.event_card(EventService().get(cup))
    assert [b["disabled"] for b in open_card["components"][0]["components"]] == [
        False,
        False,
    ]


def test_a_closed_event_greys_the_buttons_out(cup: int) -> None:
    """A finished event takes neither press, so the card says so before one."""
    set_fields(cup, end_date=TODAY - timedelta(days=1), signups_open=False)

    card = event_cards.event_card(EventService().get(cup))

    assert card["embeds"][0]["description"].splitlines()[-2] == "Signups are closed."
    assert [b["disabled"] for b in card["components"][0]["components"]] == [True, True]


def test_posting_the_card_stores_the_post_and_a_repost_edits_it(
    client: Client,
    cup: int,
    auth_headers: dict[str, str],
    discord_calls: list[tuple[str, str, Any]],
) -> None:
    """The row keeps the message so the second call edits rather than posts."""
    path = f"/events/{cup}/discord-post"
    first = client.post(path, json={"channel_id": CHANNEL}, headers=auth_headers)

    assert first.status_code == 200, first.text
    assert first.json() == {"status": "posted"}
    assert discord_calls[0][:2] == (
        "POST",
        f"https://discord.com/api/v10/channels/{CHANNEL}/messages",
    )
    with Session() as session:
        row = session.get(Season, cup)
        post = session.query(DiscordPost).one()
        assert row is not None
        assert (post.kind, post.subject_id, post.channel_id) == ("event", cup, CHANNEL)
        assert row.discord_event_id == post.message_id

    again = client.post(path, json={"channel_id": CHANNEL}, headers=auth_headers)

    assert again.json() == {"status": "edited"}
    assert discord_calls[-1][0] == "PATCH"


def test_a_press_on_sign_up_enters_the_presser(
    client: Client,
    cup: int,
    seeded: dict[str, Any],
    public_key: None,
    discord_calls: list[tuple[str, str, Any]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The entrant takes the race the profile carries and the private reply
    reads the player standard."""
    monkeypatch.setenv("FRONTEND_URL", SITE)
    send(client, press(event_cards.SIGN_UP, cup))

    assert reply(discord_calls) == (
        f"Signed up for GNL · Autumn Cup: 🇩🇪 **[P1](<{SITE}/player/P1%231111>)** (HU ?)"
    )
    entrants = EventService().get_entrants(cup)
    assert [(row.user.name if row.user else None, row.channel) for row in entrants] == [
        ("P1", "bot")
    ]

    send(client, press(event_cards.SIGN_UP, cup))
    assert reply(discord_calls) == "You are already signed up."


def test_a_press_on_check_in_stamps_the_entrant(
    client: Client,
    cup: int,
    seeded: dict[str, Any],
    public_key: None,
    discord_calls: list[tuple[str, str, Any]],
) -> None:
    """No round carries dates, so the cup checks in to itself, and the window
    opens checkin_days before the day it starts."""
    entrant = enter(cup, seeded["player_ids"][0])
    set_fields(cup, start_date=TODAY + timedelta(days=1))

    send(client, press(event_cards.CHECK_IN, cup))

    assert reply(discord_calls) == "Checked in for GNL · Autumn Cup."
    with Session() as session:
        row = session.get(EventEntrant, entrant)
        assert row is not None and row.checked_in_at is not None

    send(client, press(event_cards.CHECK_IN, cup))
    assert reply(discord_calls) == "You are already checked in."


def test_a_press_from_an_unlinked_discord_id_says_how_to_link(
    client: Client,
    cup: int,
    seeded: dict[str, Any],
    public_key: None,
    discord_calls: list[tuple[str, str, Any]],
) -> None:
    send(client, press(event_cards.SIGN_UP, cup, user="no-such-id"))

    assert reply(discord_calls) == event_cards.LINK_FIRST
    assert EventService().get_entrants(cup) == []


def test_a_shut_check_in_window_refuses_the_press(
    client: Client,
    cup: int,
    seeded: dict[str, Any],
    public_key: None,
    discord_calls: list[tuple[str, str, Any]],
) -> None:
    """The window opens checkin_days before the start and closes on the day it
    starts, and the press names the side it landed on."""
    enter(cup, seeded["player_ids"][0])
    set_fields(cup, checkin_days=0)

    send(client, press(event_cards.CHECK_IN, cup))

    assert reply(discord_calls) == event_cards.NOT_OPEN_YET

    set_fields(cup, start_date=TODAY - timedelta(days=1))
    send(client, press(event_cards.CHECK_IN, cup))

    assert reply(discord_calls) == event_cards.CHECK_IN_CLOSED


def test_an_event_with_dated_rounds_sends_the_press_to_the_round(
    client: Client,
    cup: int,
    seeded: dict[str, Any],
    public_key: None,
    discord_calls: list[tuple[str, str, Any]],
) -> None:
    """A round with dates is the check-in shape, and /availability answers it."""
    enter(cup, seeded["player_ids"][0])
    add_round(cup, TODAY, TODAY + timedelta(days=1))

    send(client, press(event_cards.CHECK_IN, cup))

    assert reply(discord_calls) == event_cards.PER_ROUND
