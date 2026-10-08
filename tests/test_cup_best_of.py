"""A cup plays a best-of per part of its bracket and vetoes its maps by it.

The stage names the best-of of a bracket part, counted back from the end; the
draw writes it onto each round. An event that vetoes by best-of derives the
veto of each series from that series' best-of and the pool, and game 1 plays
the one map the veto leaves. A GNL season keeps its own order and fixed map.
"""

from itertools import count
from typing import Any

from httpx2 import Client
from sqlmodel import col, select

from app.core import brackets
from app.core.best_of import largest_best_of, parse_plan
from app.core.db import Session
from app.core.map_order import (
    DEFAULT_RULES,
    cup_order,
    cup_rules,
    decider_of,
    maps_by_game,
)
from app.models.map import Map
from app.models.relationships import DBEventRound
from app.models.series import Series
from app.services import series_games
from tests.test_event_organizers import (
    Headers,
    Member,
    draw,
    enter,
    grant,
)
from tests.test_stage_engine import players

MAP_NUMBERS = count(1)

DOUBLE = {
    "format": "double_elimination",
    "best_of": 1,
    "best_of_by_round": "upper_final:3,lower_final:3,grand_final:5",
}


def maps(count: int) -> list[int]:
    """`count` fresh maps of the app, named apart from every map made before."""
    with Session.begin() as session:
        numbers = [next(MAP_NUMBERS) for _ in range(count)]
        rows = [Map(name=f"Map {number}", shortname=f"M{number}") for number in numbers]
        session.add_all(rows)
        session.flush()
        return [row.id for row in rows if row.id is not None]


def cup(
    client: Client, headers: Headers, stage: dict[str, Any], pool: list[int]
) -> Any:  # noqa: ANN401
    return client.post(
        "/events",
        json={
            "name": f"Map Cup {next(MAP_NUMBERS)}",
            "kind": "cup",
            "veto_by_best_of": True,
            "map_ids": pool,
            "stages": [stage],
        },
        headers=headers,
    )


def test_every_round_names_the_part_of_the_bracket_it_plays() -> None:
    single = brackets.elimination_plan(8, third_place=True)
    assert single.roles == ["quarterfinal", "semifinal", "final"]
    # a field with a play-in names the play-in as no part
    assert brackets.elimination_plan(9).roles[0] is None

    double = brackets.double_elimination_plan(8, grand_final="reset")
    named = dict(zip(double.rounds, double.roles, strict=True))
    assert named["Upper bracket round 2"] == "upper_semifinal"
    assert named["Upper bracket final"] == "upper_final"
    assert named["Lower bracket round 3"] == "lower_semifinal"
    assert named["Lower bracket final"] == "lower_final"
    assert named["Grand final"] == named["Grand final reset"] == "grand_final"
    assert named["Upper bracket round 1"] is None
    # a plan with no parts answers none for any round
    assert brackets.round_robin_plan(4, 1).role(0) is None


def test_the_stored_plan_reads_back_and_names_its_longest_series() -> None:
    assert parse_plan("semifinal:3,final:5") == {"semifinal": 3, "final": 5}
    assert parse_plan(None) == {}
    assert largest_best_of(1, "semifinal:3,final:5") == 5
    assert largest_best_of(3, None) == 3


def test_the_veto_of_a_series_follows_its_best_of() -> None:
    assert cup_rules(1) == "decider"
    assert cup_rules(3) == "decider,loser,loser"
    # seven maps: four bans leave three, two picks leave the decider
    assert cup_order(3, 7) == ["Ban_A", "Ban_B", "Ban_A", "Ban_B", "Pick_A", "Pick_B"]
    assert cup_order(1, 3) == ["Ban_A", "Ban_B"]
    assert decider_of([1, 2, 3], [1, 2], complete=True) == 3
    assert decider_of([1, 2, 3], [1], complete=False) is None


def test_a_side_that_loses_twice_plays_its_second_pick() -> None:
    queue = {"A": [11, 12], "B": [21, 22]}
    # B wins game 1 and game 2, A takes the next three: A picks game 2 and 3, B game 4 and 5
    winners = {1: "B", 2: "B", 3: "A", 4: "A"}
    offered = maps_by_game(cup_rules(5), None, {}, winners, queue=queue, decider=99)
    assert offered == {1: 99, 2: 11, 3: 12, 4: 21, 5: 22}
    # a GNL series reads its one pick a side as before
    assert maps_by_game(DEFAULT_RULES, 7, {"A": 1, "B": 2}, {1: "A"}) == {
        1: 7,
        2: 2,
        3: None,
    }


def test_the_draw_writes_each_rounds_best_of_from_the_plan(
    client: Client, auth_headers: Headers
) -> None:
    pool = maps(6)
    made = cup(client, auth_headers, DOUBLE, pool)
    assert made.status_code == 201, made.text
    event = made.json()
    assert [row["id"] for row in event["maps"]] == pool
    assert event["veto_by_best_of"] is True
    assert event["stages"][0]["best_of_by_round"] == DOUBLE["best_of_by_round"]

    enter(client, auth_headers, event["id"], players(8))
    assert draw(client, auth_headers, event).status_code == 200
    with Session.begin() as session:
        rounds = {
            row.name: row.best_of
            for row in session.scalars(
                select(DBEventRound).where(col(DBEventRound.season_id) == event["id"])
            )
        }
    assert rounds["Upper bracket round 1"] is None
    assert rounds["Upper bracket final"] == 3
    assert rounds["Lower bracket final"] == 3
    assert rounds["Grand final"] == 5

    # the series read names its own best-of and the cup's map rules
    stage = client.get(
        f"/events/{event['id']}/stages/{event['stages'][0]['id']}/series"
    ).json()
    names = {row["id"]: row["name"] for row in stage["rounds"]}
    by_round = {names[row["round_id"]]: row["rules"] for row in stage["series"]}
    assert by_round["Upper bracket round 1"] == {"map_rules": "decider", "best_of": 1}
    assert by_round["Grand final"] == {
        "map_rules": "decider,loser,loser,loser,loser",
        "best_of": 5,
    }


def test_a_cup_series_vetoes_down_to_the_decider_game_one_plays(
    client: Client, auth_headers: Headers
) -> None:
    pool = maps(3)
    event = cup(
        client, auth_headers, {"format": "single_elimination", "best_of": 1}, pool
    ).json()
    enter(client, auth_headers, event["id"], players(2))
    assert draw(client, auth_headers, event).status_code == 200
    with Session.begin() as session:
        series_id = session.scalars(select(Series)).one().id

    board = client.get(f"/player-series/{series_id}/veto", headers=auth_headers)
    assert board.status_code == 200, board.text
    assert board.json()["order"] == ["Ban_A", "Ban_B"]
    assert board.json()["map_rules"] == "decider"
    for map_id in pool[:2]:
        step = client.put(
            f"/player-series/{series_id}/veto",
            json={"action": "record", "map_id": map_id},
            headers=auth_headers,
        )
        assert step.status_code == 200, step.text
    assert step.json()["complete"] is True

    # game 1 is offered on the one map the veto left
    with Session.begin() as session:
        series = session.scalars(
            select(Series).options(*series_games._OFFER_LOADS)
        ).one()
        assert series_games._offers(session, series) == {1: pool[2]}


def test_a_pool_smaller_than_the_longest_series_is_refused(
    client: Client, auth_headers: Headers
) -> None:
    refused = cup(client, auth_headers, DOUBLE, maps(4))
    assert refused.status_code == 400
    assert "Bo5 needs 5 maps" in refused.text

    event = cup(client, auth_headers, DOUBLE, maps(5)).json()
    shrink = client.put(
        f"/events/{event['id']}/maps",
        json={"map_ids": [row["id"] for row in event["maps"]][:3]},
        headers=auth_headers,
    )
    assert shrink.status_code == 400
    # a GNL-style event vetoes by its own order and asks nothing of the pool
    plain = client.post(
        "/events",
        json={
            "name": "Plain Cup",
            "kind": "cup",
            "stages": [{"format": "single_elimination", "best_of": 5}],
        },
        headers=auth_headers,
    )
    assert plain.status_code == 201, plain.text


def test_an_organizer_sets_the_pool_of_their_own_cup_only(
    client: Client, auth_headers: Headers, member: Member
) -> None:
    grant(client, auth_headers, "71")
    headers = member("71")
    pool = maps(5)
    own = cup(client, headers, DOUBLE, pool)
    assert own.status_code == 201, own.text
    reordered = client.put(
        f"/events/{own.json()['id']}/maps",
        json={"map_ids": list(reversed(pool))},
        headers=headers,
    )
    assert reordered.status_code == 200, reordered.text
    assert [row["id"] for row in reordered.json()["maps"]] == list(reversed(pool))

    other = cup(client, auth_headers, DOUBLE, maps(5)).json()
    refused = client.put(
        f"/events/{other['id']}/maps", json={"map_ids": pool}, headers=headers
    )
    assert refused.status_code == 403
    # the ladder pool reads for an organizer, so a cup can start from it
    assert client.get("/maps/ladder-import", headers=member("72")).status_code == 403
