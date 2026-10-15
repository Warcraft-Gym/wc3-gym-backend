"""A withdrawal from a drawn cup forfeits every series the entrant still owes:
an open one at once, and one it reaches later as soon as both its sides fill."""

from typing import Any

import pytest
from httpx2 import Client
from sqlmodel import col, select

from app.core.db import Session
from app.models.base import ident
from app.models.enums import EventKind, StageFormat
from app.models.event_entrant import EventEntrant
from app.models.event_stage import EventStage
from app.models.season import Season
from tests.test_event_organizers import Member
from tests.test_stage_engine import bracket, cup, generate, players, score
from tests.test_team_cups import accept, headers_of, no_refresh, sign_up
from tests.test_team_cups import cup as team_cup


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


def users_of(event: int) -> list[int]:
    """The entrants' users in seed order, the first seed first."""
    with Session.begin() as session:
        return [
            row.user_id
            for row in session.scalars(
                select(EventEntrant)
                .where(col(EventEntrant.event_id) == event)
                .order_by(col(EventEntrant.seed))
            )
            if row.user_id is not None
        ]


def withdraw(client: Client, headers: dict[str, str], event: int, entrant: int) -> None:
    response = client.post(
        f"/events/{event}/entrants/{entrant}/withdraw", headers=headers
    )
    assert response.status_code == 204, response.text


def series_of(stage: int, user_id: int) -> list[dict[str, Any]]:
    return [row for row in bracket(stage) if user_id in row["sides"]]


def test_a_player_who_withdraws_forfeits_the_open_series_at_once(
    client: Client, auth_headers: dict[str, str], member: Member
) -> None:
    event, (stage,) = cup(4)
    generate(client, auth_headers, event, stage)
    first, *_ = users_of(event)
    response = client.delete(
        f"/events/{event}/entrants/me", headers=headers_of(member, first)
    )
    assert response.status_code == 204, response.text

    [semi] = series_of(stage, first)
    assert semi["result_kind"] == "forfeit"
    # the other side won it and stands in the final
    winner = next(side for side in semi["sides"] if side != first)
    [final] = [row for row in bracket(stage) if row["round"] == "Final"]
    assert winner in final["sides"]


def test_a_series_a_withdrawn_player_reaches_later_forfeits_when_it_fills(
    client: Client, auth_headers: dict[str, str]
) -> None:
    event, (stage,) = cup(4)
    generate(client, auth_headers, event, stage)
    first, second, *_ = users_of(event)
    semis = [row for row in bracket(stage) if row["round"] == "Semifinals"]
    top = next(row for row in semis if first in row["sides"])
    other = next(row for row in semis if row is not top)
    assert score(client, auth_headers, top["id"], 2, 0).status_code == 200
    withdraw(client, auth_headers, event, entrant_of(event, first))

    # the final waits for its second side, then forfeits to it
    [final] = [row for row in bracket(stage) if row["round"] == "Final"]
    assert final["score"] == (None, None)
    first_side = other["sides"].index(second) == 0
    assert (
        score(
            client,
            auth_headers,
            other["id"],
            2 if first_side else 0,
            0 if first_side else 2,
        ).status_code
        == 200
    )
    [final] = [row for row in bracket(stage) if row["round"] == "Final"]
    assert final["result_kind"] == "forfeit"
    won = final["sides"][0 if final["score"][0] > final["score"][1] else 1]
    assert won == second


def test_a_series_both_sides_left_is_a_forfeit_nobody_wins(
    client: Client, auth_headers: dict[str, str]
) -> None:
    event, (stage,) = cup(4)
    generate(client, auth_headers, event, stage)
    semis = [row for row in bracket(stage) if row["round"] == "Semifinals"]
    # both semi-final winners have left by the time the final fills: a runner
    # entered their results first, and the final settles by itself
    for semi in semis:
        with Session.begin() as session:
            row = session.get(EventEntrant, entrant_of(event, semi["sides"][0]))
            assert row is not None
            row.withdrawn_at = row.created_at
        assert score(client, auth_headers, semi["id"], 2, 0).status_code == 200
    [final] = [row for row in bracket(stage) if row["round"] == "Final"]
    assert (final["score"], final["result_kind"]) == ((0, 0), "forfeit")


def test_a_side_cannot_report_over_a_walkover_or_a_forfeit(
    client: Client, auth_headers: dict[str, str], member: Member
) -> None:
    """A walkover and a forfeit are a runner's: neither side reports over one,
    as neither side clears one, and a runner still does."""
    event, (stage,) = cup(4)
    generate(client, auth_headers, event, stage)
    semis = [row for row in bracket(stage) if row["round"] == "Semifinals"]
    for semi, kind in zip(semis, ("walkover", "forfeit"), strict=True):
        awarded = client.put(
            f"/cup-series/{semi['id']}/result-kind",
            json={"result_kind": kind, "winner": 1},
            headers=auth_headers,
        )
        assert awarded.status_code == 200, awarded.text
        for side, (first, second) in zip(semi["sides"], ((2, 0), (0, 2)), strict=True):
            refused = client.put(
                f"/cup-series/{semi['id']}/report",
                json={"player1_score": first, "player2_score": second},
                headers=headers_of(member, side),
            )
            assert refused.status_code == 403, refused.text
        [row] = [row for row in bracket(stage) if row["id"] == semi["id"]]
        assert (row["score"], row["result_kind"]) == ((2, 0), kind)

    corrected = client.put(
        f"/cup-series/{semis[0]['id']}/report",
        json={"player1_score": 2, "player2_score": 1},
        headers=auth_headers,
    )
    assert corrected.status_code == 200, corrected.text


def test_a_runner_report_over_a_walkover_is_a_played_result(
    client: Client, auth_headers: dict[str, str]
) -> None:
    """A runner who reports the games of a walkover makes it a played series."""
    event, (stage,) = cup(4)
    generate(client, auth_headers, event, stage)
    semi = bracket(stage)[0]
    path = f"/cup-series/{semi['id']}"
    awarded = client.put(
        f"{path}/result-kind",
        json={"result_kind": "walkover", "winner": 1},
        headers=auth_headers,
    )
    assert awarded.status_code == 200, awarded.text

    reported = client.put(
        f"{path}/report",
        json={"player1_score": 2, "player2_score": 1},
        headers=auth_headers,
    )
    assert reported.status_code == 200, reported.text
    assert reported.json()["result_kind"] == "played"
    [row] = [row for row in bracket(stage) if row["id"] == semi["id"]]
    assert (row["score"], row["result_kind"]) == ((2, 1), "played")


def test_a_withdrawn_player_acts_for_no_side(
    client: Client, auth_headers: dict[str, str], member: Member
) -> None:
    """A player who left reports, clears and vetoes for nobody, even on a
    result played before they left; they still read the board, and a runner
    still writes."""
    event, (stage,) = cup(2)
    generate(client, auth_headers, event, stage)
    [final] = bracket(stage)
    assert score(client, auth_headers, final["id"], 2, 0).status_code == 200
    loser = final["sides"][1]
    withdraw(client, auth_headers, event, entrant_of(event, loser))
    headers = headers_of(member, loser)
    path = f"/cup-series/{final['id']}"

    flipped = client.put(
        f"{path}/report", json={"player1_score": 0, "player2_score": 2}, headers=headers
    )
    assert flipped.status_code == 403, flipped.text
    assert client.delete(f"{path}/result", headers=headers).status_code == 403
    vetoed = client.put(f"{path}/veto", json={"action": "undo"}, headers=headers)
    assert vetoed.status_code == 403, vetoed.text
    assert bracket(stage)[0]["score"] == (2, 0)
    read = client.get(f"{path}/veto", headers=headers)
    assert read.status_code == 200, read.text

    assert client.delete(f"{path}/result", headers=auth_headers).status_code == 200


def test_a_withdrawn_player_loses_every_lower_bracket_series_on_the_way(
    client: Client, auth_headers: dict[str, str]
) -> None:
    event, (stage,) = cup(4, StageFormat.double_elimination)
    generate(client, auth_headers, event, stage)
    first, *_ = users_of(event)
    withdraw(client, auth_headers, event, entrant_of(event, first))
    played = [row for row in series_of(stage, first) if row["score"] != (None, None)]
    assert played and all(row["result_kind"] == "forfeit" for row in played)
    # the lower bracket series it dropped into forfeits once its other side comes
    while pending := [
        row
        for row in bracket(stage)
        if row["score"] == (None, None) and None not in row["sides"]
    ]:
        assert score(client, auth_headers, pending[0]["id"], 2, 0).status_code == 200
    assert all(row["result_kind"] == "forfeit" for row in series_of(stage, first)), (
        series_of(stage, first)
    )


def test_a_placement_bracket_plays_a_withdrawal_to_the_last_place(
    client: Client, auth_headers: dict[str, str]
) -> None:
    event, (stage,) = cup(4, StageFormat.placement)
    generate(client, auth_headers, event, stage)
    first, *_ = users_of(event)
    withdraw(client, auth_headers, event, entrant_of(event, first))
    while pending := [
        row
        for row in bracket(stage)
        if row["score"] == (None, None) and None not in row["sides"]
    ]:
        assert score(client, auth_headers, pending[0]["id"], 2, 0).status_code == 200
    rows = client.get(f"/events/{event}/stages/{stage}/standings").json()[0]["rows"]
    # a withdrawn player takes no place; the rest close up over it
    assert first not in [row["user_id"] for row in rows]
    assert [row["position"] for row in rows] == [1, 2, 3]


def test_a_runner_cannot_withdraw_from_a_koth_night_through_the_cup_route(
    client: Client, auth_headers: dict[str, str]
) -> None:
    event, _ = cup(2)
    with Session.begin() as session:
        row = session.get(Season, event)
        assert row is not None
        row.kind = EventKind.koth
    first, *_ = users_of(event)
    response = client.post(
        f"/events/{event}/entrants/{entrant_of(event, first)}/withdraw",
        headers=auth_headers,
    )
    assert response.status_code == 400, response.text


def test_a_team_that_withdraws_forfeits_its_open_series(
    client: Client,
    auth_headers: dict[str, str],
    member: Member,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    no_refresh(monkeypatch)
    event = team_cup()
    with Session.begin() as session:
        stage = EventStage(event_id=event, format=StageFormat.single_elimination)
        session.add(stage)
        session.flush()
        stage_id = ident(stage)
    ids = players(8)
    teams = []
    for index in range(4):
        captain, mate = ids[2 * index], ids[2 * index + 1]
        made = sign_up(client, event, headers_of(member, captain), f"W{index}", mate)
        assert made.status_code == 201, made.text
        team = made.json()["team"]["id"]
        accept(client, event, team, headers_of(member, mate))
        teams.append((team, captain, made.json()["id"]))
    generate(client, auth_headers, event, stage_id)
    team, captain, entrant = teams[0]
    gone = client.delete(
        f"/events/{event}/cup-teams/{team}", headers=headers_of(member, captain)
    )
    assert gone.status_code == 204, gone.text
    with Session.begin() as session:
        from app.models.cup_series import CupSeries

        [row] = session.scalars(
            select(CupSeries).where(
                (col(CupSeries.entrant1_id) == entrant)
                | (col(CupSeries.entrant2_id) == entrant)
            )
        ).all()
        assert row.result_kind == "forfeit"
