"""A cup that takes check-in draws the players who checked in.

A no-show stays signed up and is left out of the draw, so the runner needs no
step to take them out. A short team cannot check in, so it is left out
instead of holding the draw, and an unplaced no-show holds no division cut.
Fewer than two check-ins refuse the draw and say so.
"""

from collections.abc import Sequence
from typing import Any

from httpx2 import Client
from sqlmodel import col, select

from app.core.db import Session
from app.models.event_division import EventDivision
from app.models.event_entrant import EventEntrant
from app.models.season import Season
from app.models.types import utcnow
from app.services.cup_engine import NOT_CHECKED_IN
from tests.test_event_organizers import Headers, Member
from tests.test_stage_engine import bracket, cup, generate, players_of, team_cup


def takes_check_in(event: int, checked: Sequence[int | None]) -> None:
    """Turn the cup's check-in on and check the named entrants in."""
    with Session.begin() as session:
        row = session.get(Season, event)
        assert row is not None
        row.checkin_enabled = True
        for entrant in session.scalars(
            select(EventEntrant).where(col(EventEntrant.id).in_(checked))
        ):
            entrant.checked_in_at = utcnow()


def entrant_ids(event: int) -> list[int]:
    with Session.begin() as session:
        return [
            row.id
            for row in session.scalars(
                select(EventEntrant)
                .where(col(EventEntrant.event_id) == event)
                .order_by(col(EventEntrant.seed))
            )
            if row.id is not None
        ]


def drawn_players(stage: int) -> set[Any]:
    return {side for row in bracket(stage) for side in row["sides"] if side is not None}


def test_the_draw_leaves_the_no_shows_out_and_keeps_them_signed_up(
    client: Client, auth_headers: Headers
) -> None:
    event, (stage,) = cup(5)
    *showed, missing = entrant_ids(event)
    takes_check_in(event, showed)
    generate(client, auth_headers, event, stage)

    first, second, third, fourth, fifth = players_of(event)
    assert fifth not in drawn_players(stage)
    assert {first, second, third, fourth} <= drawn_players(stage)
    with Session.begin() as session:
        row = session.get(EventEntrant, missing)
        assert row is not None and row.withdrawn_at is None


def test_a_cup_without_check_in_draws_everyone(
    client: Client, auth_headers: Headers
) -> None:
    event, (stage,) = cup(4)
    generate(client, auth_headers, event, stage)
    assert set(players_of(event)) == drawn_players(stage)


def test_fewer_than_two_check_ins_refuse_the_draw(
    client: Client, auth_headers: Headers
) -> None:
    event, (stage,) = cup(4)
    takes_check_in(event, entrant_ids(event)[:1])
    refused = client.post(
        f"/events/{event}/stages/{stage}/generate", headers=auth_headers
    )
    assert refused.status_code == 400
    assert NOT_CHECKED_IN in refused.text


def test_an_unplaced_no_show_holds_no_division_draw(
    client: Client, auth_headers: Headers
) -> None:
    event, (stage,) = cup(4, divisions=1)
    *showed, missing = entrant_ids(event)
    takes_check_in(event, showed)
    with Session.begin() as session:
        row = session.get(EventEntrant, missing)
        assert row is not None
        row.division_id = None
        assert session.scalars(select(EventDivision)).first() is not None
    generate(client, auth_headers, event, stage)
    assert len(drawn_players(stage)) == 3


def test_a_short_team_that_did_not_check_in_holds_no_draw(
    client: Client, auth_headers: Headers, member: Member
) -> None:
    event, stage, team_ids, _ = team_cup(client, auth_headers, member)
    with Session.begin() as session:
        from app.models.cup_team import CupTeamMember

        # the fourth team loses a player, so it cannot check in
        gone = session.scalars(
            select(CupTeamMember).where(
                col(CupTeamMember.team_id) == team_ids[3],
                col(CupTeamMember.captain).is_(False),
            )
        ).first()
        assert gone is not None
        session.delete(gone)
    with Session.begin() as session:
        entrants = {
            row.cup_team_id: row.id
            for row in session.scalars(
                select(EventEntrant).where(col(EventEntrant.event_id) == event)
            )
        }
    takes_check_in(event, [entrants[team] for team in team_ids[:3]])
    drawn = client.post(
        f"/events/{event}/stages/{stage}/generate", headers=auth_headers
    )
    assert drawn.status_code == 200, drawn.text
    with Session.begin() as session:
        from app.models.cup_series import CupSeries

        drawn_entrants = {
            side
            for row in session.scalars(select(CupSeries))
            for side in (row.entrant1_id, row.entrant2_id)
            if side is not None
        }
    assert drawn_entrants == {entrants[team] for team in team_ids[:3]}


def test_a_runner_checks_everyone_in_and_a_short_team_stays_out(
    client: Client, auth_headers: Headers, member: Member
) -> None:
    event, stage, team_ids, _ = team_cup(client, auth_headers, member)
    with Session.begin() as session:
        from app.models.cup_team import CupTeamMember

        gone = session.scalars(
            select(CupTeamMember).where(
                col(CupTeamMember.team_id) == team_ids[3],
                col(CupTeamMember.captain).is_(False),
            )
        ).first()
        assert gone is not None
        session.delete(gone)
    takes_check_in(event, [])
    answer = client.post(
        f"/events/{event}/entrants/checkin-everyone", headers=auth_headers
    )
    assert answer.status_code == 200, answer.text
    checked = {row["team"]["name"]: row["checked_in_at"] for row in answer.json()}
    assert [name for name, at in sorted(checked.items()) if at] == ["T1", "T2", "T3"]
    assert checked["T4"] is None
    drawn = client.post(
        f"/events/{event}/stages/{stage}/generate", headers=auth_headers
    )
    assert drawn.status_code == 200, drawn.text


def test_check_everyone_in_is_a_runners_and_a_cups(
    client: Client, auth_headers: Headers, member: Member
) -> None:
    event, _ = cup(4)
    refused = client.post(
        f"/events/{event}/entrants/checkin-everyone", headers=member("9")
    )
    assert refused.status_code == 403
    # this cup takes no check-in, so there is nothing to check in
    off = client.post(
        f"/events/{event}/entrants/checkin-everyone", headers=auth_headers
    )
    assert off.status_code == 400
