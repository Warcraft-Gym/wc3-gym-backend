"""A cup closes itself on the result that plays it out, and posts its podium.

The result that completes a cup's last stage, in every division, closes the
cup: it pays the places and posts the podium in the announcement channel, one
message that pings the role and congratulates the podium by name. Each place
reads a credit line with its series record, the champion's with the final it
won, then the cup's figures and a thank-you; a cup with divisions carries a
card per division. A Swiss stage with a round left stays open, a cup played
over rounds closes when its last round is finished, and a reopen and a
corrected result close it again and edit the message.
"""

from typing import Any

from httpx2 import Client
from sqlalchemy import select
from sqlmodel import col

from app.core.db import Session
from app.models.enums import StageFormat
from app.models.event_award import EventAward
from app.models.season import Season
from app.services import cup_announcements
from tests.test_awards import play_out
from tests.test_cup_announcements import ANNOUNCE, ROLE, announcements
from tests.test_cup_divisions import field_of
from tests.test_cup_rounds import finish_leg, legs_of, rounds_cup
from tests.test_cup_swiss import draw_round, play_round
from tests.test_event_organizers import Headers
from tests.test_stage_engine import bracket, cup, generate, score

__all__ = ["announcements"]

THANKS = cup_announcements.THANKS


def closed(event: int) -> bool:
    with Session() as session:
        row = session.get(Season, event)
        assert row is not None
        return row.closed_at is not None


def places(event: int) -> list[int | None]:
    with Session() as session:
        return list(
            session.scalars(
                select(col(EventAward.place))
                .where(col(EventAward.event_id) == event)
                .order_by(col(EventAward.place))
            )
        )


def podiums(calls: list[tuple[str, str, Any]]) -> list[dict[str, Any]]:
    """Every podium message posted in the announcement channel."""
    return [
        body
        for method, url, body in calls
        if (method, url) == ("POST", ANNOUNCE) and "is over!" in body["content"]
    ]


def cards(message: dict[str, Any]) -> list[list[str]]:
    return [embed["description"].splitlines() for embed in message["embeds"]]


def test_the_last_result_closes_the_cup_and_posts_its_podium(
    client: Client, auth_headers: Headers, discord_calls: list, announcements: None
) -> None:
    event, (stage,) = cup(4, best_of=3)
    generate(client, auth_headers, event, stage)
    first, second = (row for row in bracket(stage) if row["round"] == "Semifinals")
    assert score(client, auth_headers, first["id"], 2, 0).status_code == 200
    assert score(client, auth_headers, second["id"], 2, 1).status_code == 200
    assert not closed(event)
    (final,) = (row for row in bracket(stage) if row["round"] == "Final")

    assert score(client, auth_headers, final["id"], 2, 1).status_code == 200

    assert closed(event)
    assert places(event)[:2] == [1, 2]
    (message,) = podiums(discord_calls)
    assert message["content"].startswith(
        f"<@&{ROLE}> 🏆 **Autumn Cup** is over!\nCongratulations <@90001>, <@90002>"
    )
    assert message["allowed_mentions"]["roles"] == [ROLE]
    assert {"90001", "90002"} <= set(message["allowed_mentions"]["users"])
    (card,) = cards(message)
    assert card[:3] == [
        "## 🏆 Autumn Cup",
        "🥇 **E1**, champion: 2–0 in series, won the final 2–1 against E2",
        "🥈 **E2**, runner-up: 1–1 in series",
    ]
    thirds = card[3:-4]
    assert thirds
    assert all(line.endswith(", third: 0–1 in series") for line in thirds)
    assert card[-4:] == ["", "4 players · 3 series · 8 maps", "", THANKS]

    # a Finish after it pays the places again and edits the message
    assert (
        client.post(f"/events/{event}/finish", headers=auth_headers).status_code == 200
    )
    assert len(podiums(discord_calls)) == 1
    assert discord_calls[-1][0] == "PATCH"


def test_a_cup_with_divisions_closes_with_its_last_division_a_card_each(
    client: Client, auth_headers: Headers, discord_calls: list, announcements: None
) -> None:
    event, (stage,) = cup(4, divisions=2, best_of=3)
    generate(client, auth_headers, event, stage)
    for row in bracket(stage):
        if row["round"] == "Semifinals":
            assert score(client, auth_headers, row["id"], 2, 0).status_code == 200
    finals = [row for row in bracket(stage) if row["round"] == "Final"]
    assert len(finals) == 2
    assert score(client, auth_headers, finals[0]["id"], 2, 0).status_code == 200
    # the other division still plays its final
    assert not closed(event)
    assert podiums(discord_calls) == []

    assert score(client, auth_headers, finals[1]["id"], 2, 0).status_code == 200

    assert closed(event)
    (message,) = podiums(discord_calls)
    division_one, division_two, closing = cards(message)
    assert division_one[0] == "## 🏆 Autumn Cup · Division 1"
    assert division_two[0] == "## 🏆 Autumn Cup · Division 2"
    assert division_one[1].startswith("🥇 **E") and division_two[1].startswith("🥇 **E")
    assert closing == ["8 players · 6 series · 12 maps", "", THANKS]
    # both divisions' champions and runners-up are congratulated by ping
    assert len(message["allowed_mentions"]["users"]) >= 4


def test_a_cup_past_discords_ten_cards_lists_its_last_divisions_in_the_closing_card() -> (
    None
):
    blocks: list[tuple[str | None, list[str]]] = [
        (f"Division {number}", [f"🥇 **P{number}**, champion"])
        for number in range(1, 12)
    ]

    made = cup_announcements._cards("Cup", blocks, ["8 players", "", THANKS])

    assert len(made) == 10
    assert made[8]["description"].splitlines()[0] == "## 🏆 Cup · Division 9"
    assert made[9]["description"].splitlines() == [
        "**Division 10**",
        "🥇 **P10**, champion",
        "",
        "**Division 11**",
        "🥇 **P11**, champion",
        "",
        "8 players",
        "",
        THANKS,
    ]


def test_a_swiss_stage_with_a_round_left_stays_open(
    client: Client, auth_headers: Headers
) -> None:
    event, (stage,) = cup(4, StageFormat.swiss, swiss_rounds=3, best_of=1)
    assert draw_round(client, auth_headers, event, stage).status_code == 200
    play_round(client, auth_headers, stage)
    # every series drawn so far is scored, but two rounds are still to draw
    assert not closed(event)
    for _ in range(2):
        assert draw_round(client, auth_headers, event, stage).status_code == 200
        play_round(client, auth_headers, stage)

    assert closed(event)


def test_a_cup_over_rounds_closes_with_its_last_round(
    client: Client, auth_headers: Headers, discord_calls: list, announcements: None
) -> None:
    made = rounds_cup(
        client, auth_headers, points_by_place=[10, 6, 3, 3], published=True
    )
    event = made["id"]
    field_of(event, (2000, 1900, 1800, 1700))
    for leg in legs_of(client, event):
        client.post(
            f"/events/{event}/legs/{leg['id']}/checkins/everyone",
            headers=auth_headers,
        )
        stage = leg["stage_ids"][0]
        generate(client, auth_headers, event, stage)
        play_out(client, auth_headers, stage)
        # a round played out waits for its finish, which pays its points
        assert not closed(event)
        assert finish_leg(client, auth_headers, event, leg["id"]).status_code == 200

    assert closed(event)
    (message,) = podiums(discord_calls)
    (card,) = cards(message)
    assert card[1].startswith("🥇 **")
    assert card[1].endswith(", champion: 30 pts from 3 rounds")
    assert card[-3] == "4 players · 3 rounds · 9 series"


def test_a_reopen_and_a_corrected_final_close_it_again_and_edit_the_podium(
    client: Client, auth_headers: Headers, discord_calls: list, announcements: None
) -> None:
    event, (stage,) = cup(4, best_of=3)
    generate(client, auth_headers, event, stage)
    play_out(client, auth_headers, stage)
    assert closed(event)
    assert (
        client.post(f"/events/{event}/reopen", headers=auth_headers).status_code == 200
    )
    (final,) = (row for row in bracket(stage) if row["round"] == "Final")

    assert score(client, auth_headers, final["id"], 1, 2).status_code == 200

    assert closed(event)
    assert len(podiums(discord_calls)) == 1
    method, _, body = discord_calls[-1]
    assert method == "PATCH"
    assert cards(body)[0][1] == (
        "🥇 **E2**, champion: 2–0 in series, won the final 2–1 against E1"
    )
