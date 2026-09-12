"""/availability: a public card per round; each press writes the presser's own week."""

from collections.abc import Callable
from typing import Any

from httpx2 import Client

from app.services import interactions
from app.services.availability import AvailabilityService
from tests.discord import APP_ID, CHANNEL, TOKEN, WEBHOOK, command, signed
from tests.test_availability import turn_off_scheduling


def post(client: Client, payload: dict[str, Any]) -> None:
    body, headers = signed(payload)
    assert client.post(
        "/discord/interactions", content=body, headers=headers
    ).json() == {"ok": True}


def press(user: str, custom_id: str) -> dict[str, Any]:
    return {
        "type": interactions.COMPONENT,
        "application_id": APP_ID,
        "token": TOKEN,
        "channel_id": "chan-1",
        "member": {"user": {"id": user, "username": f"p{user}"}},
        "data": {"custom_id": custom_id, "component_type": 2},
    }


def test_the_card_names_the_season_and_round_and_carries_three_buttons(
    client: Client, seeded: dict[str, Any], public_key: None, discord_calls: list
) -> None:
    """The seeded season is the current one and runs four weeks from 5 Jan 2026."""
    post(client, command("availability", user="1", round=3))

    posted = discord_calls[0]
    assert posted[:2] == ("POST", CHANNEL)
    assert posted[2]["content"].startswith("**Season 1 · Round 3** · <t:")
    assert posted[2]["content"].endswith(" — check in")
    buttons = posted[2]["components"][0]["components"]
    assert [(b["label"], b["style"], b["custom_id"]) for b in buttons] == [
        ("Check in", 3, "availability:1:3:yes"),
        ("Can't play", 4, "availability:1:3:no"),
        ("Clear", 2, "availability:1:3:clear"),
    ]


def test_without_a_round_the_card_is_for_the_current_one(
    client: Client, seeded: dict[str, Any], public_key: None, discord_calls: list
) -> None:
    """Every seeded round has ended, so the last one stands in."""
    post(client, command("availability", user="1"))

    assert discord_calls[0][2]["content"].startswith("**Season 1 · Round 4**")


def test_a_press_writes_the_pressers_own_answer(
    client: Client,
    seeded: dict[str, Any],
    public_key: None,
    discord_calls: list,
    checkin_day: Callable[[str], None],
) -> None:
    checkin_day("2026-01-19")
    post(client, press("1", "availability:1:3:no"))
    assert discord_calls[-1][:2] == ("PATCH", f"{WEBHOOK}/messages/@original")
    assert discord_calls[-1][2] == {
        "content": "Saved: you can't play round 3 of Season 1."
    }

    rows = AvailabilityService().for_user(seeded["player_ids"][0], seeded["season_id"])
    assert [(row.playday, row.available, row.set_by_user_id) for row in rows] == [
        (3, False, seeded["player_ids"][0])
    ]

    post(client, press("1", "availability:1:3:clear"))
    assert discord_calls[-1][2] == {
        "content": "Cleared your answer for round 3 of Season 1."
    }
    assert (
        AvailabilityService().for_user(seeded["player_ids"][0], seeded["season_id"])
        == []
    )


def test_a_stranger_is_told_to_link_their_account(
    client: Client, seeded: dict[str, Any], public_key: None, discord_calls: list
) -> None:
    post(client, press("999", "availability:1:3:yes"))

    assert discord_calls[-1][2]["content"].startswith(
        "Your Discord account is not linked to a player yet."
    )


def test_a_round_the_season_lacks_is_refused(
    client: Client, seeded: dict[str, Any], public_key: None, discord_calls: list
) -> None:
    post(client, command("availability", user="1", round=9))
    assert discord_calls[-1][2] == {"content": "Season 1 has no round 9."}

    post(client, press("1", "availability:1:9:yes"))
    assert discord_calls[-1][2] == {"content": "playday must be between 1 and 4"}


def test_an_event_without_scheduling_posts_no_card_and_takes_no_press(
    client: Client, seeded: dict[str, Any], public_key: None, discord_calls: list
) -> None:
    turn_off_scheduling(seeded["season_id"])
    refusal = {"content": "This event does not use availability."}

    post(client, command("availability", user="1", round=3))
    assert [call[:2] for call in discord_calls] == [
        ("PATCH", f"{WEBHOOK}/messages/@original")
    ]
    assert discord_calls[-1][2] == refusal

    post(client, press("1", "availability:1:3:no"))
    assert discord_calls[-1][2] == refusal
    assert (
        AvailabilityService().for_user(seeded["player_ids"][0], seeded["season_id"])
        == []
    )


def test_a_press_before_the_window_is_answered_privately(
    client: Client, seeded: dict[str, Any], public_key: None, discord_calls: list
) -> None:
    """The default test day is two days before round 3's check-in opens."""
    post(client, press("1", "availability:1:3:no"))

    assert discord_calls[-1][2] == {"content": "Check-in for round 3 opens on 16 Jan."}
    assert (
        AvailabilityService().for_user(seeded["player_ids"][0], seeded["season_id"])
        == []
    )
