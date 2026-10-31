"""A cup that is drawn or full puts a new signup on its waitlist; a runner lets
it in before the draw, or swaps it for a player who has not played after it.

The waitlist is the end of the cup's line: a withdrawal lets the first in line
in, a cup with divisions lets its line in a whole division at a time, and a
waiting player checks in like one who is in, though the draw never seats them.
"""

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
    """The players on the cup's waitlist, in the order it reads."""
    with Session.begin() as session:
        return [
            row.user_id
            for row in session.scalars(
                select(EventEntrant)
                .where(
                    col(EventEntrant.event_id) == event,
                    col(EventEntrant.waitlisted_at).is_not(None),
                    col(EventEntrant.withdrawn_at).is_(None),
                )
                .order_by(col(EventEntrant.waitlisted_at), col(EventEntrant.id))
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
    # a second signup is refused
    assert sign_up(client, headers_of(member, late), event).status_code == 400


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


@pytest.mark.parametrize(
    ("phase", "checked_in", "open_now", "short", "action"),
    [
        ("checkin", False, True, False, "check_in"),
        ("checkin", True, True, False, "checked_in"),
        ("checkin", False, False, False, "waitlisted"),
        # a team still waiting for an invited player takes no check-in yet
        ("checkin", False, True, True, "waitlisted"),
        # once the cup runs the waiting entry may only leave
        ("running", True, False, False, "waitlisted"),
    ],
)
def test_a_waiting_entry_checks_in_while_the_window_stands_open(
    phase: str, checked_in: bool, open_now: bool, short: bool, action: str
) -> None:
    from app.models.enums import EventKind
    from app.models.types import utcnow
    from app.services.events import _member_action

    event = Season(kind=EventKind.cup, signups_open=False)
    read = _member_action(
        phase,  # ty: ignore[invalid-argument-type]
        event,
        joined=True,
        checked_in_at=utcnow() if checked_in else None,
        checkin_open_now=open_now,
        waiting=True,
        team=short,
        short=short,
    )
    assert read == action


@pytest.mark.parametrize(
    ("total", "cap", "divisions", "taken"),
    [
        (5, None, False, 5),
        (3, 4, False, 3),
        (6, 4, False, 4),
        (4, 4, True, 4),
        (7, 4, True, 4),
        (8, 4, True, 8),
        (11, 4, True, 8),
        (12, 4, True, 12),
    ],
)
def test_the_line_takes_its_cap_or_every_division_it_fills(
    total: int, cap: int | None, divisions: bool, taken: int
) -> None:
    from app.core.waitlist import places

    assert places(total, cap, divisions) == taken


def line_cup(
    client: Client,
    headers: dict[str, str],
    cap: int,
    divisions: bool = False,
    **fields: Any,  # noqa: ANN401
) -> int:
    """A published cup made through Create cup that takes `cap` players, or
    `cap` players per division."""
    from tests.test_cup_divisions import make_cup

    return make_cup(
        client, headers, entrant_cap=cap, uses_divisions=divisions, **fields
    )["id"]


def sign_up_all(client: Client, member: Member, event: int, ids: list[int]) -> None:
    for user_id in ids:
        made = sign_up(client, headers_of(member, user_id), event)
        assert made.status_code == 201, made.text


def withdraw(client: Client, member: Member, event: int, user_id: int) -> None:
    gone = client.delete(
        f"/events/{event}/entrants/me", headers=headers_of(member, user_id)
    )
    assert gone.status_code == 204, gone.text


def entrant_of(event: int, user_id: int) -> int:
    with Session.begin() as session:
        row = session.scalars(
            select(EventEntrant).where(
                col(EventEntrant.event_id) == event,
                col(EventEntrant.user_id) == user_id,
            )
        ).one()
        assert row.id is not None
        return row.id


def test_a_cup_with_divisions_lets_its_line_in_a_whole_division_at_a_time(
    client: Client, auth_headers: dict[str, str], member: Member
) -> None:
    event = line_cup(client, auth_headers, 4, divisions=True)
    ids = players(8)

    sign_up_all(client, member, event, ids[:4])
    assert waiting(event) == []
    # past the first division the line waits for the next one to fill
    sign_up_all(client, member, event, ids[4:7])
    assert waiting(event) == ids[4:7]
    sign_up_all(client, member, event, ids[7:])
    assert waiting(event) == []

    # a withdrawal before the draw sends the players past the first division back, in line order
    withdraw(client, member, event, ids[1])
    assert waiting(event) == ids[5:8]


def test_a_withdrawal_lets_the_first_in_line_in(
    client: Client, auth_headers: dict[str, str], member: Member
) -> None:
    event = line_cup(client, auth_headers, 2)
    ids = players(4)
    sign_up_all(client, member, event, ids)
    assert waiting(event) == ids[2:]

    withdraw(client, member, event, ids[0])
    assert waiting(event) == ids[3:]


def test_a_return_signup_stands_at_the_end_of_the_line(
    client: Client, auth_headers: dict[str, str], member: Member
) -> None:
    event = line_cup(client, auth_headers, 2)
    ids = players(3)
    sign_up_all(client, member, event, ids)
    withdraw(client, member, event, ids[0])
    assert waiting(event) == []

    sign_up_all(client, member, event, ids[:1])
    assert waiting(event) == ids[:1]


def test_a_player_a_runner_adds_joins_the_line(
    client: Client, auth_headers: dict[str, str], member: Member
) -> None:
    event = line_cup(client, auth_headers, 2)
    ids = players(3)
    sign_up_all(client, member, event, ids[:2])
    # a hand-add past the places waits like a signup
    added = client.post(
        f"/events/{event}/entrants/admin",
        json={"user_id": ids[2], "race": "HU"},
        headers=auth_headers,
    )
    assert added.status_code == 201, added.text
    assert added.json()["waitlisted_at"] is not None
    assert waiting(event) == ids[2:]

    # a withdrawal lets it in, as it would a signup
    withdraw(client, member, event, ids[0])
    assert waiting(event) == []


def test_a_team_a_runner_adds_joins_the_line(
    client: Client, auth_headers: dict[str, str]
) -> None:
    from tests.test_team_cups import cup as team_cup

    event = team_cup(entrant_cap=1)
    ids = players(4)
    for name, (captain, mate) in (("First", ids[:2]), ("Second", ids[2:])):
        added = client.post(
            f"/events/{event}/cup-teams/admin",
            json={"name": name, "captain_id": captain, "member_ids": [mate]},
            headers=auth_headers,
        )
        assert added.status_code == 201, added.text
    with Session.begin() as session:
        rows = session.scalars(
            select(EventEntrant)
            .where(col(EventEntrant.event_id) == event)
            .order_by(col(EventEntrant.id))
        ).all()
        assert [row.waitlisted_at is not None for row in rows] == [False, True]


def test_a_player_a_runner_lets_in_stays_in(
    client: Client, auth_headers: dict[str, str], member: Member
) -> None:
    event = line_cup(client, auth_headers, 2, divisions=True)
    ids = players(5)
    sign_up_all(client, member, event, ids)
    assert waiting(event) == ids[4:]
    admitted = client.post(
        f"/events/{event}/entrants/{entrant_of(event, ids[4])}/admit",
        headers=auth_headers,
    )
    assert admitted.status_code == 200, admitted.text
    assert waiting(event) == []

    # three left fill one division of two: the line keeps its first two and the admitted one
    withdraw(client, member, event, ids[0])
    withdraw(client, member, event, ids[1])
    assert waiting(event) == []


def test_a_waiting_player_checks_in_and_the_draw_leaves_them_out(
    client: Client, auth_headers: dict[str, str], member: Member
) -> None:
    event = line_cup(client, auth_headers, 2, checkin_enabled=True, early_checkin=True)
    ids = players(3)
    sign_up_all(client, member, event, ids)
    late = ids[2]
    assert waiting(event) == [late]

    for user_id in ids:
        checkin = client.post(
            f"/events/{event}/entrants/{entrant_of(event, user_id)}/checkin",
            headers=headers_of(member, user_id),
        )
        assert checkin.status_code == 200, checkin.text
    mine = client.get("/me/events", headers=headers_of(member, late))
    [row] = [one for one in mine.json() if one["id"] == event]
    assert (row["action"], row["waitlisted"]) == ("checked_in", True)

    stage = client.get(f"/events/{event}").json()["stages"][0]["id"]
    generate(client, auth_headers, event, stage)
    sides = {side for row in bracket(stage) for side in row["sides"]}
    assert late not in sides and set(ids[:2]) <= sides


def test_a_cup_over_rounds_only_lets_its_line_forward_once_a_round_is_drawn(
    client: Client, auth_headers: dict[str, str], member: Member
) -> None:
    from tests.test_cup_rounds import LEGS, check_in

    event = line_cup(client, auth_headers, 2, divisions=True, legs=LEGS)
    ids = players(7)
    sign_up_all(client, member, event, ids[:4])
    first = client.get(f"/events/{event}").json()["cup_legs"][0]
    # a waiting player checks in for a round on their own
    sign_up_all(client, member, event, ids[4:5])
    assert waiting(event) == ids[4:5]
    own = check_in(client, headers_of(member, ids[4]), event, first["id"])
    assert own.status_code == 200, own.text
    assert entrant_of(event, ids[4]) in own.json()[0]["checked_in"]

    everyone = client.post(
        f"/events/{event}/legs/{first['id']}/checkins/everyone", headers=auth_headers
    )
    assert everyone.status_code == 200, everyone.text
    generate(client, auth_headers, event, first["stage_ids"][0])
    sides = {side for row in bracket(first["stage_ids"][0]) for side in row["sides"]}
    assert ids[4] not in sides

    # after the draw the line still moves forward into a place a withdrawal frees
    withdraw(client, member, event, ids[0])
    assert waiting(event) == []
    # but sends nobody back: three in line fill one division of two
    withdraw(client, member, event, ids[1])
    assert waiting(event) == []
    sign_up_all(client, member, event, ids[5:])
    assert waiting(event) == ids[6:]
    # a runner lets a waiting player in between the rounds
    admitted = client.post(
        f"/events/{event}/entrants/{entrant_of(event, ids[6])}/admit",
        headers=auth_headers,
    )
    assert admitted.status_code == 200, admitted.text
    assert waiting(event) == []


def test_a_cap_raised_by_an_edit_lets_the_line_in(
    client: Client, auth_headers: dict[str, str], member: Member
) -> None:
    event = line_cup(client, auth_headers, 2)
    ids = players(4)
    sign_up_all(client, member, event, ids)
    assert waiting(event) == ids[2:]

    edited = client.put(
        f"/events/{event}", json={"entrant_cap": 3}, headers=auth_headers
    )
    assert edited.status_code == 200, edited.text
    assert waiting(event) == ids[3:]
