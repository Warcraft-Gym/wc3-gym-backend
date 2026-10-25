"""A cup sign-up asks W3Champions about its player, and the nightly sync keeps
asking while the cup is to come.

Every cup sign-up refreshes the player's rating, whether or not the cup checks
eligibility, and once the answer is out the player's ladder games of the
current W3Champions season are read, so a cup's runners read both beside the
run page. The nightly member sync walks the players of every cup that is not
finished or cancelled, beside the GNL sign-ups. Any other event reads nothing
at a sign-up unless it checks eligibility.
"""

from datetime import timedelta
from typing import Any

import pytest
from httpx2 import Client
from sqlalchemy import update

from app.core.db import Session
from app.models.enums import EventKind, Race
from app.models.event_entrant import EventEntrant
from app.models.relationships import DBUserSeasonSignup
from app.models.types import utcnow
from app.models.user import User
from app.services import cup_ladder, events
from app.services.users import stalest_members
from tests.test_event_divisions import add_player
from tests.test_event_entrants import Member, sign_up
from tests.test_events import add_event, set_fields
from tests.test_team_cups import cup as team_cup


def record(monkeypatch: pytest.MonkeyPatch) -> tuple[list[int], list[list[int]]]:
    """The ratings a sign-up asks for and the games it reads after, neither made."""
    asked: list[int] = []
    read: list[list[int]] = []
    monkeypatch.setattr(
        events, "refresh_rating", lambda user_id, tag, *rest: asked.append(user_id)
    )
    monkeypatch.setattr(cup_ladder, "sync", lambda user_ids: read.append(user_ids))
    return asked, read


def test_a_cup_sign_up_refreshes_the_rating_and_reads_the_games_after(
    client: Client,
    seeded: dict[str, Any],
    member: Member,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asked, read = record(monkeypatch)
    # a cup that checks no eligibility still asks
    event = add_event(kind=EventKind.cup, eligibility_required=False)
    player = seeded["player_ids"][0]

    created = sign_up(client, event, member("1"))

    assert created.status_code == 201, created.text
    assert asked == [player]
    assert read == [[player]]


def test_a_hand_added_team_reads_every_player(
    client: Client,
    seeded: dict[str, Any],
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asked, read = record(monkeypatch)
    event = team_cup()
    captain, mate = seeded["player_ids"][:2]

    entered = client.post(
        f"/events/{event}/cup-teams/admin",
        json={"name": "Pair", "captain_id": captain, "member_ids": [mate]},
        headers=auth_headers,
    )

    assert entered.status_code == 201, entered.text
    assert asked == [captain, mate]
    assert read == [[captain, mate]]


def test_another_event_reads_nothing_unless_it_checks_eligibility(
    client: Client,
    seeded: dict[str, Any],
    member: Member,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    asked, read = record(monkeypatch)
    event = add_event()

    created = sign_up(client, event, member("1"))

    assert created.status_code == 201, created.text
    assert (asked, read) == ([], [])


def enter(event_id: int, user_id: int, withdrawn: bool = False) -> None:
    with Session.begin() as session:
        session.add(
            EventEntrant(
                event_id=event_id,
                user_id=user_id,
                race=Race.HU,
                withdrawn_at=utcnow() if withdrawn else None,
            )
        )


def test_the_nightly_sync_walks_the_players_of_a_cup_still_to_come(
    seeded: dict[str, Any],
) -> None:
    # a wave takes the players never synced first, so the seeded ones were synced a day ago
    with Session.begin() as session:
        session.execute(
            update(User).values(ladder_synced_at=utcnow() - timedelta(days=1))
        )
    to_come = add_event(name="To come", kind=EventKind.cup)
    finished = add_event(name="Finished", kind=EventKind.cup)
    cancelled = add_event(name="Cancelled", kind=EventKind.cup)
    set_fields(finished, closed_at=utcnow())
    set_fields(cancelled, cancelled_at=utcnow())
    playing = add_player("NightlyPlaying", {Race.HU: 1500})
    withdrawn = add_player("NightlyWithdrawn", {Race.HU: 1500})
    done = add_player("NightlyDone", {Race.HU: 1500})
    called_off = add_player("NightlyCalledOff", {Race.HU: 1500})
    gnl = add_player("NightlyGnl", {Race.HU: 1500})
    enter(to_come, playing)
    enter(to_come, withdrawn, withdrawn=True)
    enter(finished, done)
    enter(cancelled, called_off)
    with Session.begin() as session:
        session.add(
            DBUserSeasonSignup(user_id=gnl, season_id=seeded["season_id"], race=Race.HU)
        )

    walked = {user.id for user in stalest_members(utcnow())}

    # the GNL sign-ups are walked as before, and now the players of a cup to come
    assert walked == {gnl, playing}
