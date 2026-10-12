"""A cup that is drawn or full puts a new signup on its waitlist; a runner lets
it in before the draw, or swaps it for a player who has not played after it."""

from typing import Any

import pytest
from httpx2 import Client
from sqlmodel import col, select

from app.core.db import Session
from app.models.enums import StageFormat
from app.models.event_entrant import EventEntrant
from app.models.season import Season
from tests.test_event_organizers import Member
from tests.test_stage_engine import bracket, cup, generate, players
from tests.test_team_cups import headers_of


@pytest.fixture(autouse=True)
def no_refresh(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import events

    monkeypatch.setattr(events, "refresh_rating", lambda *args: None)


def open_cup(count: int, **fields: Any) -> tuple[int, int, int]:  # noqa: ANN401
    """A published cup with signups open, `count` entrants seeded, and one more
    player who has not signed up yet."""
    ids = players(count + 1)
    event, (stage,) = cup(count, StageFormat.single_elimination, ids=ids[:count])
    with Session.begin() as session:
        row = session.get(Season, event)
        assert row is not None
        row.published = True
        row.signups_open = True
        for key, value in fields.items():
            setattr(row, key, value)
    return event, stage, ids[count]


def sign_up(client: Client, headers: dict[str, str], event: int) -> Any:  # noqa: ANN401
    return client.post(
        f"/events/{event}/entrants", json={"race": "HU"}, headers=headers
    )


def waiting(event: int) -> list[int]:
    with Session.begin() as session:
        return [
            row.user_id
            for row in session.scalars(
                select(EventEntrant).where(
                    col(EventEntrant.event_id) == event,
                    col(EventEntrant.waitlisted_at).is_not(None),
                )
            )
            if row.user_id is not None
        ]


def test_a_signup_to_a_drawn_cup_waits_and_takes_no_place_in_the_bracket(
    client: Client, auth_headers: dict[str, str], member: Member
) -> None:
    event, stage, late = open_cup(4)
    generate(client, auth_headers, event, stage)
    made = sign_up(client, headers_of(member, late), event)
    assert made.status_code == 201, made.text
    assert made.json()["waitlisted_at"] is not None
    assert waiting(event) == [late]
    assert all(late not in row["sides"] for row in bracket(stage))
    # a second signup is refused; the waiting player cannot check in either
    assert sign_up(client, headers_of(member, late), event).status_code == 400
    checkin = client.post(
        f"/events/{event}/entrants/{made.json()['id']}/checkin",
        headers=headers_of(member, late),
    )
    assert checkin.status_code == 400


def test_a_full_cup_puts_the_next_signup_on_the_waitlist_and_a_runner_lets_it_in(
    client: Client, auth_headers: dict[str, str], member: Member
) -> None:
    event, stage, late = open_cup(4, entrant_cap=4)
    made = sign_up(client, headers_of(member, late), event)
    assert made.status_code == 201, made.text
    assert made.json()["waitlisted_at"] is not None

    admitted = client.post(
        f"/events/{event}/entrants/{made.json()['id']}/admit", headers=auth_headers
    )
    assert admitted.status_code == 200, admitted.text
    assert admitted.json()["waitlisted_at"] is None
    assert waiting(event) == []
    # past the cap: five play the draw
    seeds = client.put(
        f"/events/{event}/stages/{stage}/seeds",
        json={"source": "mmr"},
        headers=auth_headers,
    )
    assert seeds.status_code == 200, seeds.text
    generate(client, auth_headers, event, stage)
    assert any(late in row["sides"] for row in bracket(stage))


def test_after_the_draw_a_waiting_player_comes_in_by_a_swap_only(
    client: Client, auth_headers: dict[str, str], member: Member
) -> None:
    event, stage, late = open_cup(4)
    generate(client, auth_headers, event, stage)
    made = sign_up(client, headers_of(member, late), event)
    assert made.status_code == 201, made.text
    refused = client.post(
        f"/events/{event}/entrants/{made.json()['id']}/admit", headers=auth_headers
    )
    assert refused.status_code == 400
    assert "swap" in refused.text

    # the swap takes the waiting row in the place of a player who has not played
    with Session.begin() as session:
        out = session.scalars(
            select(EventEntrant).where(
                col(EventEntrant.event_id) == event,
                col(EventEntrant.seed) == 1,
            )
        ).one()
        out_id, out_user = out.id, out.user_id
    swapped = client.post(
        f"/events/{event}/entrants/{out_id}/replace",
        json={"user_id": late, "race": "HU"},
        headers=auth_headers,
    )
    assert swapped.status_code == 200, swapped.text
    assert waiting(event) == []
    sides = {side for row in bracket(stage) for side in row["sides"]}
    assert late in sides and out_user not in sides


def test_undoing_the_draw_keeps_the_waitlist(
    client: Client, auth_headers: dict[str, str], member: Member
) -> None:
    event, stage, late = open_cup(4)
    generate(client, auth_headers, event, stage)
    assert sign_up(client, headers_of(member, late), event).status_code == 201
    undone = client.delete(
        f"/events/{event}/stages/{stage}/series", headers=auth_headers
    )
    assert undone.status_code == 200, undone.text
    assert waiting(event) == [late]


def test_the_waiting_player_reads_waitlisted_as_their_action(
    client: Client, auth_headers: dict[str, str], member: Member
) -> None:
    event, stage, late = open_cup(4)
    generate(client, auth_headers, event, stage)
    assert sign_up(client, headers_of(member, late), event).status_code == 201
    mine = client.get("/me/events", headers=headers_of(member, late))
    assert mine.status_code == 200, mine.text
    [row] = [one for one in mine.json() if one["id"] == event]
    assert row["action"] == "waitlisted"
