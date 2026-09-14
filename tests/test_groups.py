"""A group stage: one division split into groups that merge at the next stage.

Four groups of four play a round robin of their own and keep a table each.
The top two of every group are then seeded into an eight-player bracket whose
first round holds the entrants of one group apart.
"""

from typing import Any

from httpx2 import Client
from sqlalchemy import select
from sqlmodel import col

from app.core import brackets
from app.core.db import Session
from app.models.enums import StageFormat
from app.models.event_entrant import EventEntrant
from tests.test_stage_engine import bracket, cup, generate, players_of, score


def groups_of(event: int) -> dict[int, int]:
    """The group each player was drawn into, keyed by the player."""
    with Session.begin() as session:
        return {
            row.user_id: row.group_no
            for row in session.scalars(
                select(EventEntrant).where(col(EventEntrant.event_id) == event)
            )
            if row.user_id is not None and row.group_no is not None
        }


def carried(event: int) -> list[int]:
    """The players an advance seeded, in the order it seeded them."""
    with Session.begin() as session:
        return [
            row.user_id
            for row in session.scalars(
                select(EventEntrant)
                .where(
                    col(EventEntrant.event_id) == event,
                    col(EventEntrant.seed).is_not(None),
                )
                .order_by(col(EventEntrant.seed))
            )
            if row.user_id is not None
        ]


def seeds_of(event: int) -> dict[int, int]:
    """The seed each player entered on, keyed by the player."""
    return {user: seed for seed, user in enumerate(players_of(event), start=1)}


def play_out(
    client: Client, headers: dict[str, str], stage: int, seeds: dict[int, int]
) -> None:
    """Settle every series the stage holds: the better seed takes it 2-0."""
    for row in bracket(stage):
        first, second = row["sides"]
        won = seeds[first] < seeds[second]
        done = score(client, headers, row["id"], *((2, 0) if won else (0, 2)))
        assert done.status_code == 200, done.text


def standings(client: Client, event: int, stage: int) -> list[dict[str, Any]]:
    """Every table of the stage, one per group where it plays them."""
    response = client.get(f"/events/{event}/stages/{stage}/standings")
    assert response.status_code == 200, response.text
    return response.json()


def group_cup(client: Client, headers: dict[str, str]) -> tuple[int, int, int]:
    """A cup of sixteen: four groups of four, then an eight-player bracket."""
    event, (first, second) = cup(
        16,
        StageFormat.round_robin,
        stages=2,
        group_size=4,
        group_advance=2,
    )
    assert generate(client, headers, event, first) == {"series": 24, "rounds": 3}
    return event, first, second


def test_the_snake_deal_hands_every_group_the_same_strength() -> None:
    assert brackets.snake_groups(list(range(1, 17)), 4) == [
        [1, 8, 9, 16],
        [2, 7, 10, 15],
        [3, 6, 11, 14],
        [4, 5, 12, 13],
    ]


def test_sixteen_entrants_are_dealt_into_four_groups_of_four(
    client: Client, auth_headers: dict[str, str]
) -> None:
    event, _, _ = group_cup(client, auth_headers)
    groups = groups_of(event)
    seeds = seeds_of(event)
    assert sorted(groups.values()) == sorted([1, 2, 3, 4] * 4)
    # The deal turns at the end of every pass, so seed 1 and seed 8 meet
    assert [groups[user] for user, _ in sorted(seeds.items(), key=lambda x: x[1])] == [
        1,
        2,
        3,
        4,
        4,
        3,
        2,
        1,
        1,
        2,
        3,
        4,
        4,
        3,
        2,
        1,
    ]


def test_every_group_plays_six_series_and_nobody_plays_another_group(
    client: Client, auth_headers: dict[str, str]
) -> None:
    event, stage, _ = group_cup(client, auth_headers)
    groups = groups_of(event)
    rows = bracket(stage)
    assert len(rows) == 24
    played = [groups[first] for first, second in (row["sides"] for row in rows)]
    assert sorted(played) == sorted([1, 2, 3, 4] * 6)
    for row in rows:
        first, second = row["sides"]
        assert groups[first] == groups[second]
    # The three rounds are shared, the way two divisions share them
    assert len({row["number"] for row in rows}) == 3


def test_the_stage_answers_one_table_per_group(
    client: Client, auth_headers: dict[str, str]
) -> None:
    event, stage, _ = group_cup(client, auth_headers)
    play_out(client, auth_headers, stage, seeds_of(event))
    tables = standings(client, event, stage)
    assert [table["group_no"] for table in tables] == [1, 2, 3, 4]
    assert [table["group_name"] for table in tables] == [
        "Group A",
        "Group B",
        "Group C",
        "Group D",
    ]
    assert [table["division_id"] for table in tables] == [None] * 4
    assert [len(table["rows"]) for table in tables] == [4] * 4
    # Inside a group the better seed took every series, so the table is 3-2-1-0
    assert [row["points"] for row in tables[0]["rows"]] == [3, 2, 1, 0]


def test_two_from_every_group_seed_a_bracket_that_holds_them_apart(
    client: Client, auth_headers: dict[str, str]
) -> None:
    event, stage, playoff = group_cup(client, auth_headers)
    seeds = seeds_of(event)
    groups = groups_of(event)
    play_out(client, auth_headers, stage, seeds)
    moved = client.post(f"/events/{event}/stages/{stage}/advance", headers=auth_headers)
    assert moved.status_code == 200, moved.text
    assert moved.json() == {"seeded": 8}
    # The groups merge here, so nobody carries one into the bracket
    assert groups_of(event) == {}
    # The four winners lead the draw, then the four runners-up
    assert [seeds[user] for user in carried(event)] == [1, 2, 3, 4, 8, 7, 6, 5]
    assert generate(client, auth_headers, event, playoff) == {"series": 7, "rounds": 3}
    drawn = bracket(playoff)
    quarters = [row for row in drawn if row["number"] == drawn[0]["number"]]
    assert len(quarters) == 4
    for row in quarters:
        first, second = row["sides"]
        assert groups[first] != groups[second]


def test_a_group_stage_refuses_a_field_it_cannot_split(
    client: Client, auth_headers: dict[str, str]
) -> None:
    """Three entrants in groups of two leave a group of one, which plays nobody."""
    event, (stage,) = cup(3, StageFormat.round_robin, group_size=2)
    response = client.post(
        f"/events/{event}/stages/{stage}/generate", headers=auth_headers
    )
    assert response.status_code == 400
    assert "group needs two entrants" in response.json()["error"]


def test_an_admin_writes_the_group_settings_and_the_engine_refuses_a_bad_one(
    client: Client, auth_headers: dict[str, str]
) -> None:
    event, _ = cup(4, StageFormat.round_robin)
    body = [{"format": "round_robin", "group_size": 4, "group_advance": 2}]
    response = client.put(f"/events/{event}/stages", json=body, headers=auth_headers)
    assert response.status_code == 200, response.text
    stage = response.json()["stages"][0]
    assert (stage["group_size"], stage["group_advance"]) == (4, 2)
    for bad in ({"group_size": 1}, {"group_advance": 0}):
        refused = client.put(
            f"/events/{event}/stages", json=[bad], headers=auth_headers
        )
        assert refused.status_code == 422
