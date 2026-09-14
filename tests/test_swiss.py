"""A Swiss stage, drawn round by round through the routes an admin drives.

Bench row 15: eight entrants play three rounds, the weakest seed takes every
series, one of them is awarded instead of played, no pair is drawn twice, and
Buchholz breaks the tie the points and the game difference leave.
"""

from typing import Any

from httpx2 import Client
from sqlalchemy import select
from sqlmodel import col

from app.core.db import Session
from app.models.enums import StageFormat
from app.models.event_entrant import EventEntrant
from tests.test_stage_engine import bracket, cup, players_of, score

# The order the rounds are drawn in is read back from the seeds, so a table is
# a list of seed numbers, 1 the strongest
SWISS_TABLE = [8, 4, 7, 3, 6, 2, 5, 1]
# The same eight under a rule that reads points and the game difference alone
POINTS_TABLE = [8, 3, 4, 7, 2, 5, 6, 1]


def swiss(count: int, **fields: Any) -> tuple[int, list[int]]:  # noqa: ANN401
    """A cup whose first stage plays `count` entrants off in a Swiss."""
    fields.setdefault("swiss_rounds", 3)
    fields.setdefault("points_series_won", 3)
    fields.setdefault("points_series_drawn", 1)
    return cup(count, StageFormat.swiss, **fields)


def seeds_of(event: int) -> dict[int, int]:
    """The seed each player entered on, keyed by the player."""
    return {user: seed for seed, user in enumerate(players_of(event), start=1)}


def draw(client: Client, headers: dict[str, str], event: int, stage: int) -> Any:  # noqa: ANN401
    response = client.post(f"/events/{event}/stages/{stage}/rounds", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def play(
    client: Client,
    headers: dict[str, str],
    event: int,
    stage: int,
    seeds: dict[int, int],
    award: bool = False,
) -> Any:  # noqa: ANN401
    """Draw one round and settle it: the weaker seed takes every series.

    `award` gives the first series of the round to its winner as a walkover,
    so a round that was not played out still ranks.
    """
    drawn = draw(client, headers, event, stage)
    for row in bracket(stage):
        if row["score"] != (None, None):
            continue
        first, second = row["sides"]
        to_first = seeds[first] > seeds[second]
        if award:
            done = client.put(
                f"/series/{row['id']}/result-kind",
                json={"result_kind": "walkover", "winner": 1 if to_first else 2},
                headers=headers,
            )
            award = False
        else:
            done = score(client, headers, row["id"], *((2, 0) if to_first else (0, 2)))
        assert done.status_code == 200, done.text
    return drawn


def table(client: Client, event: int, stage: int, seeds: dict[int, int]) -> list[int]:
    """The seed numbers of one division's table, best place first."""
    rows = client.get(f"/events/{event}/stages/{stage}/standings").json()[0]["rows"]
    return [seeds[row["user_id"]] for row in rows]


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


def pairings(stage: int) -> list[frozenset[int | None]]:
    """The two sides of every series the stage holds."""
    return [frozenset(row["sides"]) for row in bracket(stage)]


def test_eight_entrants_play_three_rounds_and_meet_nobody_twice(
    client: Client, auth_headers: dict[str, str]
) -> None:
    event, (stage,) = swiss(8)
    seeds = seeds_of(event)
    first = play(client, auth_headers, event, stage, seeds, award=True)
    # The route answers the round it drew and nothing else
    assert [row["name"] for row in first["rounds"]] == ["Round 1"]
    assert len(first["series"]) == 4
    play(client, auth_headers, event, stage, seeds)
    play(client, auth_headers, event, stage, seeds)
    rows = bracket(stage)
    assert len(rows) == 12
    assert len(set(pairings(stage))) == 12
    # One of the twelve was awarded to its winner, not played out
    assert [row["result_kind"] for row in rows].count("walkover") == 1
    # An even field draws no bye, so every side of every series is a player
    played = [seeds[side] for row in rows for side in row["sides"]]
    assert sorted(set(played)) == list(range(1, 9))
    assert all(played.count(seed) == 3 for seed in range(1, 9))


def test_the_next_round_waits_on_the_round_before_and_stops_at_the_count(
    client: Client, auth_headers: dict[str, str]
) -> None:
    event, (stage,) = swiss(8)
    seeds = seeds_of(event)
    draw(client, auth_headers, event, stage)
    early = client.post(f"/events/{event}/stages/{stage}/rounds", headers=auth_headers)
    assert early.status_code == 400
    assert "result first" in early.text
    for row in bracket(stage):
        first, second = row["sides"]
        assert (
            score(
                client,
                auth_headers,
                row["id"],
                *((2, 0) if seeds[first] > seeds[second] else (0, 2)),
            ).status_code
            == 200
        )
    play(client, auth_headers, event, stage, seeds)
    play(client, auth_headers, event, stage, seeds)
    over = client.post(f"/events/{event}/stages/{stage}/rounds", headers=auth_headers)
    assert over.status_code == 400
    assert "3 rounds" in over.text


def test_buchholz_breaks_the_tie_the_points_and_the_games_leave(
    client: Client, auth_headers: dict[str, str]
) -> None:
    """Seeds 7 and 3 finish level on points and on games, and never met.

    Buchholz, the sum of the opponents' points, puts seed 7 above seed 3; the
    table of a stage whose ranking_rule leaves Buchholz out reads the other way.
    """
    event, (stage,) = swiss(8)
    seeds = seeds_of(event)
    for _ in range(3):
        play(client, auth_headers, event, stage, seeds)
    assert table(client, event, stage, seeds) == SWISS_TABLE
    rows = {
        seeds[row["user_id"]]: row
        for row in client.get(f"/events/{event}/stages/{stage}/standings").json()[0][
            "rows"
        ]
    }
    assert (rows[7]["points"], rows[7]["game_diff"]) == (
        rows[3]["points"],
        rows[3]["game_diff"],
    )
    assert frozenset(players_of(event)[index] for index in (6, 2)) not in pairings(
        stage
    )


def test_the_ranking_rule_names_the_order_the_table_reads(
    client: Client, auth_headers: dict[str, str]
) -> None:
    event, (stage,) = swiss(8, ranking_rule="points,game_diff")
    seeds = seeds_of(event)
    for _ in range(3):
        play(client, auth_headers, event, stage, seeds)
    assert table(client, event, stage, seeds) == POINTS_TABLE


def test_an_odd_field_gives_the_bye_to_the_lowest_entrant_without_one(
    client: Client, auth_headers: dict[str, str]
) -> None:
    event, (stage,) = swiss(7)
    seeds = seeds_of(event)
    for _ in range(3):
        play(client, auth_headers, event, stage, seeds)
    byes = [row for row in bracket(stage) if row["sides"][1] is None]
    assert [seeds[row["sides"][0]] for row in byes] == [7, 5, 3]
    # A bye is a walkover the drawing awards, so the round needs no result
    assert [row["result_kind"] for row in byes] == ["walkover"] * 3
    assert [row["score"] for row in byes] == [(2, 0)] * 3


def test_a_stage_ended_after_two_rounds_advances_the_table_as_it_stands(
    client: Client, auth_headers: dict[str, str]
) -> None:
    event, (first, second) = swiss(8, stages=2, advance_count=4)
    seeds = seeds_of(event)
    play(client, auth_headers, event, first, seeds)
    play(client, auth_headers, event, first, seeds)
    assert table(client, event, first, seeds) == [4, 8, 2, 3, 6, 7, 1, 5]
    moved = client.post(f"/events/{event}/stages/{first}/advance", headers=auth_headers)
    assert moved.status_code == 200, moved.text
    assert moved.json() == {"seeded": 4}
    # The playoff plays the four the table sent through, in its order
    assert [seeds[user] for user in carried(event)] == [4, 8, 2, 3]
    assert client.post(
        f"/events/{event}/stages/{second}/generate", headers=auth_headers
    ).json() == {"series": 3, "rounds": 2}


def test_a_bracket_stage_draws_no_round_of_its_own(
    client: Client, auth_headers: dict[str, str]
) -> None:
    event, (stage,) = cup(4)
    refused = client.post(
        f"/events/{event}/stages/{stage}/rounds", headers=auth_headers
    )
    assert refused.status_code == 400
    assert "one by one" in refused.text


def test_a_reader_cannot_draw_a_round(client: Client) -> None:
    event, (stage,) = swiss(4)
    assert client.post(f"/events/{event}/stages/{stage}/rounds").status_code == 401
