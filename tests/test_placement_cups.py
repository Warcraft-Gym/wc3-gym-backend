"""The placement bracket: every round splits each group into its winners and
its losers, so the last round decides every place."""

from typing import Any

import pytest
from httpx2 import Client
from sqlmodel import col, select

from app.core import brackets
from app.core.db import Session
from app.models.base import ident
from app.models.cup_series import CupSeries
from app.models.enums import StageFormat
from app.models.event_stage import EventStage
from app.models.relationships import DBEventRound
from tests.test_awards import finish, play_out
from tests.test_event_organizers import Member
from tests.test_stage_engine import bracket, cup, generate, players, stage_series
from tests.test_team_cups import accept, headers_of, no_refresh, sign_up
from tests.test_team_cups import cup as team_cup


def positions(client: Client, event: int, stage: int) -> list[int]:
    table = client.get(f"/events/{event}/stages/{stage}/standings")
    assert table.status_code == 200, table.text
    return [row["position"] for row in table.json()[0]["rows"]]


def test_sixteen_players_play_four_rounds_and_every_place() -> None:
    plan = brackets.placement_plan(16)
    assert plan.rounds == ["Round 1", "Round 2", "Round 3", "Last round", "Final"]
    assert len(plan.series) == 32
    assert plan.roles == [None, None, None, "last_round", "final"]
    # the final is the one series of places 1 and 2, in a round of its own
    [final] = [row for row in plan.series if plan.rounds[row.round] == "Final"]
    assert plan.places[final.index] == (1, 2)
    assert [(group.first, group.last) for group in plan.finish] == [
        (place, place) for place in range(1, 17)
    ]


def test_one_loss_plays_a_single_elimination_with_shared_places() -> None:
    plan = brackets.placement_plan(16, lives=1)
    assert len(plan.series) == 15
    assert [(group.first, group.last) for group in plan.finish] == [
        (1, 1),
        (2, 2),
        (3, 4),
        (5, 8),
        (9, 16),
    ]


def test_two_losses_stop_a_run_and_share_the_group() -> None:
    plan = brackets.placement_plan(16, lives=2)
    shared = [
        (group.first, group.last) for group in plan.finish if group.first < group.last
    ]
    assert shared == [(7, 8), (11, 12), (13, 16)]


def test_a_field_off_the_power_of_two_closes_its_places_up() -> None:
    for field in range(2, 17):
        plan = brackets.placement_plan(field)
        places = sorted(
            place
            for group in plan.finish
            for place in range(group.first, group.last + 1)
        )
        assert places == list(range(1, field + 1)), field
        # a series is written only for two sides that both come
        assert all(
            row.slot1 != brackets.Slot() and row.slot2 != brackets.Slot()
            for row in plan.series
        )


def test_eight_players_play_out_every_place_and_the_awards_follow(
    client: Client, auth_headers: dict[str, str]
) -> None:
    event, (stage,) = cup(8, StageFormat.placement)
    assert generate(client, auth_headers, event, stage)["series"] == 12
    read = stage_series(client, event, stage)
    by_round = {row["id"]: row["name"] for row in read["rounds"]}
    first_round = [
        row for row in read["series"] if by_round[row["round_id"]] == "Round 1"
    ]
    assert {(row["place_from"], row["place_to"]) for row in first_round} == {(1, 8)}

    play_out(client, auth_headers, stage)
    assert positions(client, event, stage) == list(range(1, 9))
    places = sorted(award["place"] for award in finish(client, auth_headers, event))
    assert places == list(range(1, 9))


def test_one_loss_shares_the_places_of_the_group_it_stops_in(
    client: Client, auth_headers: dict[str, str]
) -> None:
    event, (stage,) = cup(8, StageFormat.placement, placement_lives=1)
    assert generate(client, auth_headers, event, stage)["series"] == 7
    play_out(client, auth_headers, stage)
    assert positions(client, event, stage) == [1, 2, 3, 3, 5, 5, 5, 5]


def test_six_players_pass_their_byes_and_take_places_one_to_six(
    client: Client, auth_headers: dict[str, str]
) -> None:
    event, (stage,) = cup(6, StageFormat.placement)
    generate(client, auth_headers, event, stage)
    play_out(client, auth_headers, stage)
    rows = bracket(stage)
    assert all(row["score"] != (None, None) for row in rows)
    assert all(None not in row["sides"] for row in rows)
    assert positions(client, event, stage) == list(range(1, 7))


def test_the_last_round_and_the_final_play_their_own_best_of(
    client: Client, auth_headers: dict[str, str]
) -> None:
    event, (stage,) = cup(
        8,
        StageFormat.placement,
        best_of=1,
        best_of_by_round="last_round:3,final:5",
    )
    generate(client, auth_headers, event, stage)
    with Session.begin() as session:
        rounds = {
            row.name: row.best_of
            for row in session.scalars(
                select(DBEventRound).where(col(DBEventRound.stage_id) == stage)
            )
        }
    assert rounds == {"Round 1": None, "Round 2": None, "Last round": 3, "Final": 5}


def test_a_drawn_placement_bracket_is_taken_back_and_drawn_again(
    client: Client, auth_headers: dict[str, str]
) -> None:
    event, (stage,) = cup(4, StageFormat.placement)
    generate(client, auth_headers, event, stage)
    undone = client.delete(
        f"/events/{event}/stages/{stage}/series", headers=auth_headers
    )
    assert undone.status_code == 200, undone.text
    assert bracket(stage) == []
    assert generate(client, auth_headers, event, stage)["series"] == 4


def test_the_series_read_names_each_groups_places(
    client: Client, auth_headers: dict[str, str]
) -> None:
    event, (stage,) = cup(8, StageFormat.placement)
    generate(client, auth_headers, event, stage)
    play_out(client, auth_headers, stage)
    read: dict[str, Any] = stage_series(client, event, stage)
    by_round = {row["id"]: row["name"] for row in read["rounds"]}
    groups: dict[str, set[tuple[int, int]]] = {}
    for row in read["series"]:
        groups.setdefault(by_round[row["round_id"]], set()).add(
            (row["place_from"], row["place_to"])
        )
    assert groups == {
        "Round 1": {(1, 8)},
        "Round 2": {(1, 4), (5, 8)},
        "Last round": {(3, 4), (5, 6), (7, 8)},
        "Final": {(1, 2)},
    }


def test_four_teams_play_every_place_with_their_rosters(
    client: Client,
    auth_headers: dict[str, str],
    member: Member,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    no_refresh(monkeypatch)
    event = team_cup()
    with Session.begin() as session:
        stage = EventStage(event_id=event, format=StageFormat.placement, best_of=1)
        session.add(stage)
        session.flush()
        stage_id = ident(stage)
    ids = players(8)
    for index in range(4):
        captain, mate = ids[2 * index], ids[2 * index + 1]
        made = sign_up(client, event, headers_of(member, captain), f"P{index}", mate)
        assert made.status_code == 201, made.text
        accept(client, event, made.json()["team"]["id"], headers_of(member, mate))
    seeds = client.put(
        f"/events/{event}/stages/{stage_id}/seeds",
        json={"source": "mmr"},
        headers=auth_headers,
    )
    assert seeds.status_code == 200, seeds.text
    assert generate(client, auth_headers, event, stage_id)["series"] == 4
    with Session.begin() as session:
        sizes = session.scalars(
            select(CupSeries.side_size).where(
                col(CupSeries.round_id).in_(
                    select(DBEventRound.id).where(
                        col(DBEventRound.stage_id) == stage_id
                    )
                )
            )
        ).all()
    assert sizes == [2, 2, 2, 2]
