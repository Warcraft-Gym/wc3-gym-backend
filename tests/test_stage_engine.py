"""The stage engine: generating a stage, following its results and its table.

Every test drives the routes an admin drives, so the rounds, the sequences
and the feeder graph read back the way the run page reads them.
"""

from collections.abc import Callable
from typing import Any

import pytest
from httpx2 import Client
from sqlalchemy import select
from sqlmodel import col

from app.core.db import Session
from app.core.exceptions import BadRequestError
from app.models.base import ident
from app.models.enums import EventKind, Race, StageFormat
from app.models.event_division import EventDivision
from app.models.event_entrant import EventEntrant
from app.models.event_stage import EventStage
from app.models.relationships import DBEventRound
from app.models.season import Season
from app.models.series import Series
from app.models.team import Team
from app.models.user import User
from app.services import stage_engine
from tests.test_events import phase


def players(count: int) -> list[int]:
    """`count` fresh players, the strongest first."""
    with Session.begin() as session:
        rows = [
            User(
                name=f"E{number}",
                battleTag=f"E{number}#{number:04d}",
                discordTag=f"e{number}",
                discordId=f"9{number:04d}",
                race=Race.HU,
                mmr=2000 - number,
            )
            for number in range(1, count + 1)
        ]
        session.add_all(rows)
        session.flush()
        return [ident(row) for row in rows]


def cup(
    count: int,
    fmt: StageFormat = StageFormat.single_elimination,
    divisions: int = 0,
    stages: int = 1,
    **fields: Any,  # noqa: ANN401
) -> tuple[int, list[int]]:
    """An event whose first stage plays `count` seeded entrants per division."""
    ids = players(count * max(divisions, 1))
    with Session.begin() as session:
        event = Season(
            name="Autumn Cup", kind=EventKind.cup, series_per_round=1, published=True
        )
        session.add(event)
        session.flush()
        rows = [EventStage(event_id=ident(event), position=1, format=fmt, **fields)]
        for position in range(2, stages + 1):
            rows.append(
                EventStage(
                    event_id=ident(event),
                    position=position,
                    format=StageFormat.single_elimination,
                )
            )
        bands = [
            EventDivision(
                event_id=ident(event), position=position, name=f"Division {position}"
            )
            for position in range(1, divisions + 1)
        ]
        session.add_all(rows + bands)
        session.flush()
        for index, user_id in enumerate(ids):
            band = bands[index // count] if bands else None
            session.add(
                EventEntrant(
                    event_id=ident(event),
                    user_id=user_id,
                    race=Race.HU,
                    seed=index % count + 1,
                    division_id=ident(band) if band else None,
                )
            )
        session.flush()
        return ident(event), [ident(row) for row in rows]


def generate(client: Client, headers: dict[str, str], event: int, stage: int) -> Any:  # noqa: ANN401
    response = client.post(f"/events/{event}/stages/{stage}/generate", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def bracket(stage: int) -> list[dict[str, Any]]:
    """Every series of the stage, in play order, as plain values."""
    with Session.begin() as session:
        rounds = {
            ident(row): (row.number, row.name)
            for row in session.scalars(
                select(DBEventRound).where(col(DBEventRound.stage_id) == stage)
            )
        }
        rows = session.scalars(
            select(Series).where(col(Series.round_id).in_(list(rounds)))
        ).all()
        return sorted(
            (
                {
                    "id": ident(row),
                    "round": rounds[round_id][1],
                    "number": rounds[round_id][0],
                    "sequence": row.sequence,
                    "division_id": row.division_id,
                    "sides": (row.player1_id, row.player2_id),
                    "score": (row.player1_score, row.player2_score),
                    "result_kind": row.result_kind,
                    "slot1": (row.slot1_from_series_id, row.slot1_takes_loser),
                    "slot2": (row.slot2_from_series_id, row.slot2_takes_loser),
                }
                for row in rows
                if (round_id := row.round_id) is not None
            ),
            key=lambda row: (row["number"], row["sequence"] or 0, row["id"]),
        )


def names(rows: list[dict[str, Any]]) -> list[str]:
    """The round of the stage each series is played in, in play order."""
    seen: list[str] = []
    for row in rows:
        if row["round"] not in seen:
            seen.append(row["round"])
    return seen


def score(
    client: Client, headers: dict[str, str], series_id: int, first: int, second: int
) -> Any:  # noqa: ANN401
    return client.put(
        f"/series/{series_id}",
        json={"player1_score": first, "player2_score": second},
        headers=headers,
    )


def test_nine_entrants_play_one_play_in_and_eight_series_in_all(
    client: Client, auth_headers: dict[str, str]
) -> None:
    """Seeds 8 and 9 play the play-in; the other seven wait in the quarterfinals."""
    event, (stage,) = cup(9)
    assert generate(client, auth_headers, event, stage) == {"series": 8, "rounds": 4}
    rows = bracket(stage)
    assert names(rows) == ["Play-in", "Quarterfinals", "Semifinals", "Final"]
    seeds = players_of(event)
    play_in = [row for row in rows if row["round"] == "Play-in"]
    assert len(play_in) == 1
    # The two weakest seeds play for the last quarterfinal place
    assert play_in[0]["sides"] == (seeds[7], seeds[8])
    quarters = [row for row in rows if row["round"] == "Quarterfinals"]
    # Seven seeds skip the play-in and sit in a quarterfinal from the start
    seated = [side for row in quarters for side in row["sides"] if side is not None]
    assert len(seated) == 7
    # The eighth quarterfinal slot waits on the play-in
    fed = [
        row
        for row in quarters
        if play_in[0]["id"] in (row["slot1"][0], row["slot2"][0])
    ]
    assert len(fed) == 1
    assert [row["sequence"] for row in quarters] == [1, 2, 3, 4]


def test_thirteen_entrants_play_five_play_in_series(
    client: Client, auth_headers: dict[str, str]
) -> None:
    event, (stage,) = cup(13)
    assert generate(client, auth_headers, event, stage) == {"series": 12, "rounds": 4}
    rows = bracket(stage)
    assert len([row for row in rows if row["round"] == "Play-in"]) == 5
    quarters = [row for row in rows if row["round"] == "Quarterfinals"]
    assert len([side for row in quarters for side in row["sides"] if side]) == 3


def test_a_third_place_series_closes_the_final_round(
    client: Client, auth_headers: dict[str, str]
) -> None:
    event, (stage,) = cup(4, third_place=True)
    assert generate(client, auth_headers, event, stage) == {"series": 4, "rounds": 2}
    final = [row for row in bracket(stage) if row["round"] == "Final"]
    assert [row["sequence"] for row in final] == [1, 2]
    # The third place series takes the two the semifinals send down
    assert (final[1]["slot1"][1], final[1]["slot2"][1]) == (True, True)


def test_eight_entrants_double_elimination_end_in_a_grand_final(
    client: Client, auth_headers: dict[str, str]
) -> None:
    event, (stage,) = cup(8, StageFormat.double_elimination)
    assert generate(client, auth_headers, event, stage) == {"series": 14, "rounds": 8}
    rows = bracket(stage)
    assert names(rows) == [
        "Upper bracket round 1",
        "Upper bracket round 2",
        "Upper bracket final",
        "Lower bracket round 1",
        "Lower bracket round 2",
        "Lower bracket round 3",
        "Lower bracket final",
        "Grand final",
    ]
    by_round = {row["round"]: row for row in reversed(rows)}
    grand, upper, lower = (
        by_round["Grand final"],
        by_round["Upper bracket final"],
        by_round["Lower bracket final"],
    )
    assert grand["slot1"] == (upper["id"], False)
    assert grand["slot2"] == (lower["id"], False)
    # The lower bracket opens on the four the first upper round sends down
    first = [row for row in rows if row["round"] == "Lower bracket round 1"]
    assert all(row["slot1"][1] and row["slot2"][1] for row in first)


def test_a_padded_double_elimination_settles_its_byes(
    client: Client, auth_headers: dict[str, str]
) -> None:
    """Six entrants pad to eight: the two padded pairs are walkovers, and the
    lower bracket series they feed becomes one as soon as its other side lands."""
    event, (stage,) = cup(6, StageFormat.double_elimination)
    generate(client, auth_headers, event, stage)
    rows = bracket(stage)
    seeds = players_of(event)
    first = [row for row in rows if row["round"] == "Upper bracket round 1"]
    walkovers = [row for row in first if row["result_kind"] == "walkover"]
    assert len(walkovers) == 2
    assert [row["score"] for row in walkovers] == [(2, 0), (2, 0)]
    # The winner of a padded pair already stands in the round above it
    second = [row for row in rows if row["round"] == "Upper bracket round 2"]
    assert seeds[0] in second[0]["sides"]
    # A lower bracket series fed by a padded pair waits on its other side
    lower = [row for row in rows if row["round"] == "Lower bracket round 1"]
    assert lower[0]["score"] == (None, None)
    played = [row for row in first if row["result_kind"] == "played"]
    score(client, auth_headers, played[0]["id"], 2, 0)
    settled = next(row for row in bracket(stage) if row["id"] == lower[0]["id"])
    assert settled["result_kind"] == "walkover"
    assert settled["score"] in ((2, 0), (0, 2))


def test_five_entrants_round_robin_meet_every_pair_once(
    client: Client, auth_headers: dict[str, str]
) -> None:
    event, (stage,) = cup(5, StageFormat.round_robin)
    assert generate(client, auth_headers, event, stage) == {"series": 10, "rounds": 5}
    rows = bracket(stage)
    assert names(rows) == [f"Round {number}" for number in range(1, 6)]
    pairs = {frozenset(row["sides"]) for row in rows}
    assert len(pairs) == 10
    assert all(row["slot1"] == (None, False) for row in rows)


def test_eight_entrants_play_two_series_a_round_over_four_rounds(
    client: Client, auth_headers: dict[str, str]
) -> None:
    """Two per entrant per round covers the seven opponents in four rounds.

    Seven circle rounds pair two to a round, so the last round is the short
    one: three rounds of eight series and one of four, every pair once.
    """
    event, (stage,) = cup(8, StageFormat.round_robin, series_per_entrant_per_round=2)
    assert generate(client, auth_headers, event, stage) == {"series": 28, "rounds": 4}
    rows = bracket(stage)
    assert names(rows) == [f"Round {number}" for number in range(1, 5)]
    per_round = [
        len([row for row in rows if row["number"] == number])
        for number in sorted({row["number"] for row in rows})
    ]
    assert per_round == [8, 8, 8, 4]
    # Every entrant plays two different opponents in each full round
    for number in sorted({row["number"] for row in rows})[:3]:
        sides = [
            side for row in rows if row["number"] == number for side in row["sides"]
        ]
        assert sorted(sides) == sorted(players_of(event) * 2)
    pairs = [frozenset(row["sides"]) for row in rows]
    assert len(set(pairs)) == len(pairs) == 28


def test_an_odd_field_sits_one_entrant_out_of_every_round(
    client: Client, auth_headers: dict[str, str]
) -> None:
    """Seven entrants pair six a round, so a bye falls in each circle round."""
    event, (stage,) = cup(7, StageFormat.round_robin, series_per_entrant_per_round=2)
    assert generate(client, auth_headers, event, stage) == {"series": 21, "rounds": 4}
    rows = bracket(stage)
    field = players_of(event)
    counts = [
        sorted(
            sum(player in row["sides"] for row in rows if row["number"] == number)
            for player in field
        )
        for number in sorted({row["number"] for row in rows})
    ]
    # Two circle rounds to a round, each with its own bye; the short last
    # round is one circle round, so one entrant sits it out whole
    assert counts == [[1, 1, 2, 2, 2, 2, 2]] * 3 + [[0, 1, 1, 1, 1, 1, 1]]
    pairs = [frozenset(row["sides"]) for row in rows]
    assert len(set(pairs)) == len(pairs) == 21


def test_a_koth_chain_of_four_runs_in_one_round(
    client: Client, auth_headers: dict[str, str]
) -> None:
    """Seeds 1 and 2 open and the winner meets the next seed, in sequence."""
    event, (stage,) = cup(4, StageFormat.koth)
    assert generate(client, auth_headers, event, stage) == {"series": 3, "rounds": 1}
    rows = bracket(stage)
    assert [row["sequence"] for row in rows] == [1, 2, 3]
    seeds = players_of(event)
    assert rows[0]["sides"] == (seeds[0], seeds[1])
    assert rows[1]["slot1"] == (rows[0]["id"], False)
    assert rows[1]["sides"] == (None, seeds[2])
    assert rows[2]["slot1"] == (rows[1]["id"], False)
    assert rows[2]["sides"] == (None, seeds[3])


def players_of(event: int) -> list[int]:
    """The entrants of the event in seed order."""
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


def test_a_result_fills_the_series_below_it(
    client: Client, auth_headers: dict[str, str]
) -> None:
    event, (stage,) = cup(4, StageFormat.koth)
    generate(client, auth_headers, event, stage)
    rows = bracket(stage)
    seeds = players_of(event)
    assert score(client, auth_headers, rows[0]["id"], 2, 0).status_code == 200
    after = bracket(stage)
    assert after[1]["sides"] == (seeds[0], seeds[2])
    # The third series still waits on the second
    assert after[2]["sides"] == (None, seeds[3])
    assert score(client, auth_headers, after[1]["id"], 0, 2).status_code == 200
    assert bracket(stage)[2]["sides"] == (seeds[2], seeds[3])


def test_a_walkover_scores_a_series_with_no_games(
    client: Client, auth_headers: dict[str, str]
) -> None:
    event, (stage,) = cup(4, StageFormat.koth)
    generate(client, auth_headers, event, stage)
    rows = bracket(stage)
    seeds = players_of(event)
    response = client.put(
        f"/series/{rows[0]['id']}/result-kind",
        json={"result_kind": "walkover", "winner": 2},
        headers=auth_headers,
    )
    assert response.status_code == 200, response.text
    assert (response.json()["player1_score"], response.json()["player2_score"]) == (
        0,
        2,
    )
    after = bracket(stage)
    assert after[0]["result_kind"] == "walkover"
    # The walkover carries its winner on like any other result
    assert after[1]["sides"] == (seeds[1], seeds[2])
    # A series that already holds a result refuses a second one
    refused = client.put(
        f"/series/{rows[0]['id']}/result-kind",
        json={"result_kind": "forfeit", "winner": 1},
        headers=auth_headers,
    )
    assert refused.status_code == 400


def test_a_reopen_is_refused_while_a_later_series_is_scored(
    client: Client, auth_headers: dict[str, str]
) -> None:
    """Clearing a score takes the side back off everything below it."""
    event, (stage,) = cup(4, StageFormat.koth)
    generate(client, auth_headers, event, stage)
    rows = bracket(stage)
    seeds = players_of(event)
    score(client, auth_headers, rows[0]["id"], 2, 0)
    score(client, auth_headers, rows[1]["id"], 2, 0)
    clear = {"player1_score": None, "player2_score": None}
    refused = client.put(f"/series/{rows[0]['id']}", json=clear, headers=auth_headers)
    assert refused.status_code == 400
    assert "force" in refused.json()["error"]
    assert bracket(stage)[1]["score"] == (2, 0)

    forced = client.put(
        f"/series/{rows[0]['id']}?force=true", json=clear, headers=auth_headers
    )
    assert forced.status_code == 200, forced.text
    after = bracket(stage)
    assert after[0]["score"] == (None, None)
    assert after[1]["score"] == (None, None)
    assert after[1]["sides"] == (None, seeds[2])
    # A reopen with nothing scored below it needs no force
    score(client, auth_headers, after[0]["id"], 2, 0)
    plain = client.put(f"/series/{after[0]['id']}", json=clear, headers=auth_headers)
    assert plain.status_code == 200, plain.text
    assert bracket(stage)[1]["sides"] == (None, seeds[2])


def test_a_corrected_winner_re_points_the_series_below(
    client: Client, auth_headers: dict[str, str]
) -> None:
    """One PUT that turns a semifinal around moves the final's side with it."""
    event, (stage,) = cup(4)
    generate(client, auth_headers, event, stage)
    rows = bracket(stage)
    first, second = rows[0]["sides"]
    score(client, auth_headers, rows[0]["id"], 2, 0)
    assert bracket(stage)[2]["sides"] == (first, None)
    # The admin saved the result backwards and corrects it in place
    assert score(client, auth_headers, rows[0]["id"], 0, 2).status_code == 200
    final = bracket(stage)[2]
    assert final["sides"] == (second, None)
    assert first not in final["sides"]


def test_a_corrected_winner_is_refused_while_the_final_is_scored(
    client: Client, auth_headers: dict[str, str]
) -> None:
    """Turning a semifinal around loses the final, so it takes the same force."""
    event, (stage,) = cup(4)
    generate(client, auth_headers, event, stage)
    rows = bracket(stage)
    first, second = rows[0]["sides"]
    score(client, auth_headers, rows[0]["id"], 2, 0)
    score(client, auth_headers, rows[1]["id"], 2, 0)
    final_id = bracket(stage)[2]["id"]
    score(client, auth_headers, final_id, 2, 0)
    refused = score(client, auth_headers, rows[0]["id"], 0, 2)
    assert refused.status_code == 400
    assert "force" in refused.json()["error"]
    held = bracket(stage)
    assert held[0]["score"] == (2, 0)
    assert held[2]["sides"][0] == first
    assert held[2]["score"] == (2, 0)

    flipped = client.put(
        f"/series/{rows[0]['id']}?force=true",
        json={"player1_score": 0, "player2_score": 2},
        headers=auth_headers,
    )
    assert flipped.status_code == 200, flipped.text
    after = bracket(stage)
    assert after[0]["score"] == (0, 2)
    assert after[2]["sides"][0] == second
    assert after[2]["score"] == (None, None)


def test_a_corrected_score_with_the_same_winner_leaves_the_final_alone(
    client: Client, auth_headers: dict[str, str]
) -> None:
    """A 2-0 fixed to 2-1 sends the same player on, so nothing below it moves."""
    event, (stage,) = cup(4)
    generate(client, auth_headers, event, stage)
    rows = bracket(stage)
    score(client, auth_headers, rows[0]["id"], 2, 0)
    score(client, auth_headers, rows[1]["id"], 2, 0)
    before = bracket(stage)[2]
    score(client, auth_headers, before["id"], 2, 0)
    # The final carries a result and needs no force, because it does not move
    assert score(client, auth_headers, rows[0]["id"], 2, 1).status_code == 200
    final = bracket(stage)[2]
    assert final["sides"] == before["sides"]
    assert final["score"] == (2, 0)


def test_the_standings_read_the_points_the_stage_pays(
    client: Client, auth_headers: dict[str, str]
) -> None:
    event, (stage,) = cup(
        4,
        StageFormat.round_robin,
        points_series_won=3,
        points_series_drawn=1,
        points_game_won=0,
    )
    generate(client, auth_headers, event, stage)
    seeds = players_of(event)
    for row in bracket(stage):
        first = row["sides"][0] == seeds[0] or row["sides"][1] != seeds[0]
        score(client, auth_headers, row["id"], 2 if first else 0, 0 if first else 2)
    table = client.get(f"/events/{event}/stages/{stage}/standings").json()
    assert len(table) == 1
    rows = table[0]["rows"]
    assert [row["position"] for row in rows] == [1, 2, 3, 4]
    assert rows[0]["user_id"] == seeds[0]
    assert rows[0]["points"] == 9
    assert (rows[0]["won"], rows[0]["played"]) == (3, 3)


def test_a_koth_table_puts_the_last_winner_on_the_throne(
    client: Client, auth_headers: dict[str, str]
) -> None:
    event, (stage,) = cup(4, StageFormat.koth)
    generate(client, auth_headers, event, stage)
    seeds = players_of(event)
    rows = bracket(stage)
    score(client, auth_headers, rows[0]["id"], 2, 0)
    score(client, auth_headers, bracket(stage)[1]["id"], 2, 0)
    score(client, auth_headers, bracket(stage)[2]["id"], 0, 2)
    table = client.get(f"/events/{event}/stages/{stage}/standings").json()[0]["rows"]
    # The last series crowned the fourth seed, whatever the rest of the table says
    assert table[0]["user_id"] == seeds[3]


def test_an_elimination_table_ranks_by_the_round_reached(
    client: Client, auth_headers: dict[str, str]
) -> None:
    event, (stage,) = cup(4)
    generate(client, auth_headers, event, stage)
    seeds = players_of(event)
    rows = bracket(stage)
    score(client, auth_headers, rows[0]["id"], 2, 0)
    score(client, auth_headers, rows[1]["id"], 2, 0)
    final = bracket(stage)[2]
    score(client, auth_headers, final["id"], 0, 2)
    table = client.get(f"/events/{event}/stages/{stage}/standings").json()[0]["rows"]
    assert [row["user_id"] for row in table][:2] == [final["sides"][1], seeds[0]]


def test_advance_seeds_the_next_stage_with_the_top_places(
    client: Client, auth_headers: dict[str, str]
) -> None:
    event, (first, second) = cup(
        4, StageFormat.round_robin, stages=2, advance_count=2, points_series_won=3
    )
    generate(client, auth_headers, event, first)
    seeds = players_of(event)
    early = client.post(f"/events/{event}/stages/{first}/advance", headers=auth_headers)
    assert early.status_code == 400
    for row in bracket(first):
        won = row["sides"][0] == seeds[0] or row["sides"][1] != seeds[0]
        score(client, auth_headers, row["id"], 2 if won else 0, 0 if won else 2)
    moved = client.post(f"/events/{event}/stages/{first}/advance", headers=auth_headers)
    assert moved.status_code == 200, moved.text
    assert moved.json() == {"seeded": 2}
    with Session.begin() as session:
        rows = session.scalars(
            select(EventEntrant).where(col(EventEntrant.event_id) == event)
        ).all()
        carried = {row.user_id: (row.seed, row.seed_source) for row in rows}
    assert carried[seeds[0]] == (1, "previous_stage")
    assert sorted(seed for seed, _ in carried.values() if seed) == [1, 2]
    # The second stage plays the two that came through and nobody else
    assert generate(client, auth_headers, event, second) == {"series": 1, "rounds": 1}


def test_auto_advance_runs_on_the_last_result(
    client: Client, auth_headers: dict[str, str]
) -> None:
    event, (first, _) = cup(
        4, StageFormat.round_robin, stages=2, advance_count=2, auto_advance=True
    )
    generate(client, auth_headers, event, first)
    seeds = players_of(event)
    for row in bracket(first):
        won = row["sides"][0] == seeds[0] or row["sides"][1] != seeds[0]
        score(client, auth_headers, row["id"], 2 if won else 0, 0 if won else 2)
    with Session.begin() as session:
        seeded = [
            row.seed_source
            for row in session.scalars(
                select(EventEntrant).where(
                    col(EventEntrant.event_id) == event,
                    col(EventEntrant.seed).is_not(None),
                )
            )
        ]
    assert seeded == ["previous_stage", "previous_stage"]


def test_two_divisions_share_the_rounds_and_hold_their_own_brackets(
    client: Client, auth_headers: dict[str, str]
) -> None:
    event, (stage,) = cup(4, divisions=2)
    assert generate(client, auth_headers, event, stage) == {"series": 6, "rounds": 2}
    rows = bracket(stage)
    bands = {row["division_id"] for row in rows}
    assert len(bands) == 2 and None not in bands
    assert names(rows) == ["Semifinals", "Final"]
    table = client.get(f"/events/{event}/stages/{stage}/standings").json()
    assert len(table) == 2
    assert [division["division_name"] for division in table] == [
        "Division 1",
        "Division 2",
    ]


def test_a_gnl_stage_is_drafted_and_refuses_to_generate(
    client: Client, auth_headers: dict[str, str]
) -> None:
    event, (stage,) = cup(4, StageFormat.gnl)
    response = client.post(
        f"/events/{event}/stages/{stage}/generate", headers=auth_headers
    )
    assert response.status_code == 400
    assert "drafted" in response.json()["error"]


def test_a_stage_that_holds_series_refuses_a_second_generate(
    client: Client, auth_headers: dict[str, str]
) -> None:
    event, (stage,) = cup(4)
    generate(client, auth_headers, event, stage)
    response = client.post(
        f"/events/{event}/stages/{stage}/generate", headers=auth_headers
    )
    assert response.status_code == 400
    assert len(bracket(stage)) == 3


def test_a_reader_cannot_generate_or_advance(client: Client) -> None:
    event, (stage,) = cup(4)
    for path in ("generate", "advance"):
        assert client.post(f"/events/{event}/stages/{stage}/{path}").status_code == 401


def test_scoring_a_gnl_series_moves_nothing(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    """A GNL series carries no feeders, so the engine writes nothing for it."""
    with Session.begin() as session:
        row = session.scalars(select(Series).order_by(col(Series.id))).first()
        assert row is not None
        series_id = ident(row)
        before = {
            other.id: (other.player1_id, other.player2_id, other.player1_score)
            for other in session.scalars(select(Series))
        }
    assert score(client, auth_headers, series_id, 2, 0).status_code == 200
    with Session.begin() as session:
        after = {
            other.id: (other.player1_id, other.player2_id, other.player1_score)
            for other in session.scalars(select(Series))
        }
    assert {key: value for key, value in after.items() if key != series_id} == {
        key: value for key, value in before.items() if key != series_id
    }


def test_the_table_of_an_advanced_stage_keeps_every_entrant(
    client: Client, auth_headers: dict[str, str]
) -> None:
    """Advance seeds the next stage; the finished one still holds its whole field."""
    event, (first, _) = cup(
        4, StageFormat.round_robin, stages=2, advance_count=2, points_series_won=3
    )
    generate(client, auth_headers, event, first)
    seeds = players_of(event)
    for row in bracket(first):
        won = row["sides"][0] == seeds[0] or row["sides"][1] != seeds[0]
        score(client, auth_headers, row["id"], 2 if won else 0, 0 if won else 2)
    path = f"/events/{event}/stages/{first}/standings"
    before = client.get(path).json()[0]["rows"]
    assert len(before) == 4
    moved = client.post(f"/events/{event}/stages/{first}/advance", headers=auth_headers)
    assert moved.status_code == 200, moved.text
    after = client.get(path).json()[0]["rows"]
    assert [row["user_id"] for row in after] == [row["user_id"] for row in before]


def run_double_elimination(
    client: Client, headers: dict[str, str], upper_takes_final: bool
) -> list[dict[str, Any]]:
    """Four entrants down to the grand final, won by the side the caller names."""
    event, (stage,) = cup(
        4, StageFormat.double_elimination, grand_final_modifier="reset"
    )
    generate(client, headers, event, stage)
    for name in (
        "Upper bracket round 1",
        "Upper bracket final",
        "Lower bracket round 1",
        "Lower bracket final",
    ):
        for row in bracket(stage):
            if row["round"] == name:
                score(client, headers, row["id"], 2, 0)
    final = next(row for row in bracket(stage) if row["round"] == "Grand final")
    score(client, headers, final["id"], *((2, 0) if upper_takes_final else (0, 2)))
    return bracket(stage)


def test_a_bracket_reset_is_a_walkover_when_the_upper_side_wins(
    client: Client, auth_headers: dict[str, str]
) -> None:
    """The upper bracket side kept the title in the first final, so nobody plays
    the second one and the stage is finished."""
    rows = run_double_elimination(client, auth_headers, upper_takes_final=True)
    final, reset = rows[-2], rows[-1]
    assert reset["round"] == "Grand final reset"
    assert reset["result_kind"] == "walkover"
    assert reset["score"] == (2, 0)
    assert reset["sides"] == (final["sides"][0], final["sides"][1])


def test_a_bracket_reset_is_played_when_the_lower_side_wins(
    client: Client, auth_headers: dict[str, str]
) -> None:
    """The lower bracket side earned a second final, which is played."""
    rows = run_double_elimination(client, auth_headers, upper_takes_final=False)
    final, reset = rows[-2], rows[-1]
    assert reset["score"] == (None, None)
    assert reset["sides"] == (final["sides"][1], final["sides"][0])


def test_a_skipped_grand_final_ends_on_the_lower_bracket_final(
    client: Client, auth_headers: dict[str, str]
) -> None:
    event, (stage,) = cup(
        4, StageFormat.double_elimination, grand_final_modifier="skip"
    )
    assert generate(client, auth_headers, event, stage) == {"series": 5, "rounds": 4}
    assert "Grand final" not in names(bracket(stage))


def test_an_admin_writes_the_switches_the_engine_reads(
    client: Client, auth_headers: dict[str, str]
) -> None:
    """Third place, the grand final modifier and auto advance are stage fields."""
    event, _ = cup(4)
    body = [
        {
            "format": "double_elimination",
            "third_place": True,
            "grand_final_modifier": "reset",
            "auto_advance": True,
        }
    ]
    response = client.put(f"/events/{event}/stages", json=body, headers=auth_headers)
    assert response.status_code == 200, response.text
    stage = response.json()["stages"][0]
    assert stage["third_place"] is True
    assert stage["grand_final_modifier"] == "reset"
    assert stage["auto_advance"] is True
    refused = client.put(
        f"/events/{event}/stages",
        json=[{"grand_final_modifier": "both"}],
        headers=auth_headers,
    )
    assert refused.status_code == 422


def stage_series(client: Client, event: int, stage: int, **kwargs: Any) -> Any:  # noqa: ANN401
    """The rounds and the series of one stage, the way the run page reads them."""
    response = client.get(f"/events/{event}/stages/{stage}/series", **kwargs)
    assert response.status_code == 200, response.text
    return response.json()


def test_the_run_page_reads_the_rounds_and_the_series_of_a_stage(
    client: Client, auth_headers: dict[str, str]
) -> None:
    """Four entrants answer two rounds and three series; only the final is fed."""
    event, (stage,) = cup(4)
    generate(client, auth_headers, event, stage)
    body = stage_series(client, event, stage)
    assert [(row["number"], row["name"]) for row in body["rounds"]] == [
        (1, "Semifinals"),
        (2, "Final"),
    ]
    rows = body["series"]
    assert len(rows) == 3
    semis, final = rows[:2], rows[2]
    assert [row["round_id"] for row in semis] == [body["rounds"][0]["id"]] * 2
    assert final["round_id"] == body["rounds"][1]["id"]
    assert [row["sequence"] for row in rows] == [1, 2, 1]
    for row in semis:
        assert row["slot1_from_series_id"] is None
        assert row["slot2_from_series_id"] is None
    assert final["slot1_from_series_id"] == semis[0]["id"]
    assert final["slot2_from_series_id"] == semis[1]["id"]
    assert (final["slot1_takes_loser"], final["slot2_takes_loser"]) == (False, False)
    seeds = players_of(event)
    assert semis[0]["player1"]["id"] == seeds[0]
    assert [row["division_id"] for row in rows] == [None, None, None]
    assert [row["result_kind"] for row in rows] == ["played"] * 3
    assert [row["side_size"] for row in rows] == [1, 1, 1]
    assert [row["pick_rule"] for row in rows] == [None, None, None]


def test_a_gnl_stage_answers_its_series_with_a_round_and_no_feeders(
    client: Client, seeded: dict[str, Any]
) -> None:
    """A GNL season is drafted, so its series hang off a round and feed nothing."""
    event = seeded["season_id"]
    with Session.begin() as session:
        stage = EventStage(event_id=event, position=1, format=StageFormat.gnl)
        session.add(stage)
        session.flush()
        rounds = session.scalars(
            select(DBEventRound).where(col(DBEventRound.season_id) == event)
        ).all()
        for row in rounds:
            row.stage_id = ident(stage)
        first = min(rounds, key=lambda row: row.number)
        for row in session.scalars(select(Series)):
            row.round_id = ident(first)
        stage_id, round_id = ident(stage), ident(first)

    body = stage_series(client, event, stage_id)
    assert [row["number"] for row in body["rounds"]] == [1, 2, 3, 4]
    rows = body["series"]
    assert {row["id"] for row in rows} == {
        seeded["series_played_id"],
        seeded["series_open_id"],
    }
    for row in rows:
        assert row["round_id"] == round_id
        assert row["sequence"] is None
        assert row["division_id"] is None
        assert row["slot1_from_series_id"] is None
        assert row["slot2_from_series_id"] is None
    played = next(row for row in rows if row["id"] == seeded["series_played_id"])
    # The derived fields are filled the way every other series read fills them
    assert (played["player1_score"], played["player2_score"]) == (2, 1)
    assert played["player1_points"] == 2
    assert played["match"]["id"] == seeded["match_id"]


def test_a_stage_of_another_event_is_not_found(
    client: Client, auth_headers: dict[str, str]
) -> None:
    event, (stage,) = cup(4)
    with Session.begin() as session:
        other = Season(name="Winter Cup", kind=EventKind.cup, series_per_round=1)
        session.add(other)
        session.flush()
        other_id = ident(other)
    unknown = client.get(f"/events/{event}/stages/{stage + 9999}/series")
    assert unknown.status_code == 404
    # A stage of another event is not this event's stage
    assert client.get(f"/events/{other_id}/stages/{stage}/series").status_code == 404


def test_a_member_and_a_reader_both_read_a_stage(
    client: Client,
    auth_headers: dict[str, str],
    member: Callable[..., dict[str, str]],
) -> None:
    """The stage read is open, like every other event read."""
    event, (stage,) = cup(4)
    generate(client, auth_headers, event, stage)
    anonymous = stage_series(client, event, stage)
    signed_in = stage_series(client, event, stage, headers=member())
    assert len(anonymous["series"]) == len(signed_in["series"]) == 3


def join(event: int, division: int | None, name: str) -> int:
    """One more entrant of the event, in the division named."""
    with Session.begin() as session:
        user = User(
            name=name,
            battleTag=f"{name}#1111",
            discordTag=name.lower(),
            discordId=f"8{name}",
            race=Race.HU,
            mmr=1500,
        )
        session.add(user)
        session.flush()
        row = EventEntrant(
            event_id=event, user_id=ident(user), race=Race.HU, division_id=division
        )
        session.add(row)
        session.flush()
        return ident(row)


def divisions_of(event: int) -> list[int]:
    """The divisions of the event, the strongest first."""
    with Session.begin() as session:
        return [
            ident(row)
            for row in session.scalars(
                select(EventDivision)
                .where(col(EventDivision.event_id) == event)
                .order_by(col(EventDivision.position))
            )
        ]


def append(
    client: Client, headers: dict[str, str], event: int, stage: int, entrant: int
) -> Any:  # noqa: ANN401
    return client.post(
        f"/events/{event}/stages/{stage}/series",
        json={"entrant_id": entrant},
        headers=headers,
    )


def test_a_challenger_joins_the_chain_after_two_results(
    client: Client, auth_headers: dict[str, str]
) -> None:
    """The third series is fed by the second, and the king fills its front side."""
    event, (stage,) = cup(3, StageFormat.koth)
    generate(client, auth_headers, event, stage)
    rows = bracket(stage)
    seeds = players_of(event)
    assert score(client, auth_headers, rows[0]["id"], 2, 0).status_code == 200
    assert score(client, auth_headers, rows[1]["id"], 2, 0).status_code == 200
    entrant = join(event, None, "Challenger")
    response = append(client, auth_headers, event, stage, entrant)
    assert response.status_code == 200, response.text
    added = response.json()
    assert added["sequence"] == 3
    assert added["slot1_from_series_id"] == rows[1]["id"]
    after = bracket(stage)
    assert len(after) == 3
    # Seed 1 held the throne through both series, so he stands in the third
    assert after[2]["sides"] == (seeds[0], added["player2_id"])
    assert added["player2_id"] not in seeds


def test_a_challenger_waits_while_the_chain_is_unscored(
    client: Client, auth_headers: dict[str, str]
) -> None:
    """The new series carries its feeder and an empty front side."""
    event, (stage,) = cup(2, StageFormat.koth)
    generate(client, auth_headers, event, stage)
    opener = bracket(stage)[0]
    entrant = join(event, None, "Waiting")
    assert append(client, auth_headers, event, stage, entrant).status_code == 200
    added = bracket(stage)[1]
    assert (added["sequence"], added["sides"][0]) == (2, None)
    assert added["slot1"] == (opener["id"], False)


def test_a_single_elimination_stage_takes_no_challenger(
    client: Client, auth_headers: dict[str, str]
) -> None:
    event, (stage,) = cup(4)
    generate(client, auth_headers, event, stage)
    entrant = join(event, None, "Late")
    response = append(client, auth_headers, event, stage, entrant)
    assert response.status_code == 400, response.text
    assert "chain" in response.json()["error"]


def test_a_chain_with_no_series_refuses_a_challenger(
    client: Client, auth_headers: dict[str, str]
) -> None:
    """Two entrants open the chain before a third joins it."""
    event, (stage,) = cup(2, StageFormat.koth)
    entrant = join(event, None, "First")
    response = append(client, auth_headers, event, stage, entrant)
    assert response.status_code == 400, response.text
    assert "no series yet" in response.json()["error"]


def test_an_entrant_of_another_division_is_refused(
    client: Client, auth_headers: dict[str, str]
) -> None:
    """A challenger grows the chain of his own division, never a neighbour's."""
    event, (stage,) = cup(2, StageFormat.koth, divisions=2)
    generate(client, auth_headers, event, stage)
    weaker = divisions_of(event)[1]
    entrant = join(event, weaker, "Outsider")
    with Session.begin() as session:
        stage_row = session.get(EventStage, stage)
        bands = [session.get(EventDivision, band) for band in divisions_of(event)]
        entrant_row = session.get(EventEntrant, entrant)
        assert stage_row is not None and entrant_row is not None
        with pytest.raises(BadRequestError, match="division"):
            stage_engine.append_to_chain(session, stage_row, bands[0], entrant_row)
    # His own division still takes him, at the end of its chain
    response = append(client, auth_headers, event, stage, entrant)
    assert response.status_code == 200, response.text
    assert (response.json()["sequence"], response.json()["division_id"]) == (2, weaker)


def test_a_cup_reads_running_on_the_first_result_and_finished_on_the_last(
    client: Client, auth_headers: dict[str, str]
) -> None:
    """A bracket series names a round and no fixture, and the phase counts it
    through that round: four entrants read running once one of the three
    series is scored and finished once all three are."""
    event, (stage,) = cup(4)
    generate(client, auth_headers, event, stage)
    # The cup still takes signups, and no series has started
    assert phase(client, event) == "signups_open"

    rows = stage_series(client, event, stage)["series"]
    assert len(rows) == 3
    semis = [row for row in rows if row["player1_id"] is not None]
    assert len(semis) == 2

    assert score(client, auth_headers, semis[0]["id"], 2, 0).status_code == 200
    assert phase(client, event) == "running"

    assert score(client, auth_headers, semis[1]["id"], 2, 0).status_code == 200
    played = {row["id"] for row in semis}
    final = next(
        row
        for row in stage_series(client, event, stage)["series"]
        if row["id"] not in played
    )
    assert score(client, auth_headers, final["id"], 2, 0).status_code == 200
    assert phase(client, event) == "finished"


def team_cup(
    client: Client, auth: dict[str, str], member: Callable[..., dict[str, str]]
) -> tuple[int, int, list[int], list[list[str]]]:
    """A 2v2 cup of four pre-made teams.

    Eight players, two to a team, each team rostered against the cup and
    entered by its captain, which is the first player of its roster. The
    rosters come back as the Discord ids the players sign in with.
    """
    ids = players(8)
    with Session.begin() as session:
        event = Season(
            name="Team Cup", kind=EventKind.cup, series_per_round=1, published=True
        )
        session.add(event)
        session.flush()
        stage = EventStage(
            event_id=ident(event),
            position=1,
            format=StageFormat.single_elimination,
        )
        teams = [Team(name=f"T{number}") for number in range(1, 5)]
        session.add_all([stage, *teams])
        session.flush()
        event_id, stage_id = ident(event), ident(stage)
        team_ids = [ident(team) for team in teams]
    rosters = [ids[place * 2 : place * 2 + 2] for place in range(4)]
    for place, (team_id, roster) in enumerate(zip(team_ids, rosters, strict=True)):
        base = f"/teams/{team_id}/seasons/{event_id}"
        added = client.post(
            f"{base}/players", json={"player_ids": roster}, headers=auth
        )
        assert added.status_code == 200, added.text
        seated = client.put(
            f"{base}/captains", json={"captain_ids": roster[:1]}, headers=auth
        )
        assert seated.status_code == 200, seated.text
        entered = client.post(
            f"/events/{event_id}/entrants",
            json={"team_id": team_id},
            headers=member(f"9{place * 2 + 1:04d}"),
        )
        assert entered.status_code == 201, entered.text
    tags = [[f"9{place * 2 + seat:04d}" for seat in (1, 2)] for place in range(4)]
    return event_id, stage_id, team_ids, tags


def test_a_2v2_cup_of_four_teams_draws_a_bracket_of_entrant_sides(
    client: Client, auth_headers: dict[str, str], member: Callable[..., dict[str, str]]
) -> None:
    """A team side names its entrant and no user, and a side holds the roster."""
    event, stage, team_ids, _ = team_cup(client, auth_headers, member)

    assert generate(client, auth_headers, event, stage) == {"series": 3, "rounds": 2}

    rows = stage_series(client, event, stage)["series"]
    assert all(row["player1_id"] is None and row["player2_id"] is None for row in rows)
    assert all(row["side_size"] == 2 for row in rows)
    semis = [row for row in rows if row["entrant1_id"] is not None]
    assert len(semis) == 2
    # Every team stands in a semifinal, and the box prints its name
    assert {row["team1"]["name"] for row in semis} | {
        row["team2"]["name"] for row in semis
    } == {"T1", "T2", "T3", "T4"}
    assert {row["team1"]["id"] for row in semis} <= set(team_ids)


def test_a_roster_member_reports_a_team_series_and_a_stranger_may_not(
    client: Client,
    auth_headers: dict[str, str],
    member: Callable[..., dict[str, str]],
    replay_uploaded: Callable[..., None],
) -> None:
    """The side is the team, so either of its two players reports for it."""
    event, stage, _, rosters = team_cup(client, auth_headers, member)
    generate(client, auth_headers, event, stage)
    first = next(
        row
        for row in stage_series(client, event, stage)["series"]
        if row["entrant1_id"] is not None
    )
    replay_uploaded(first["id"], 1, 2)

    # The second player of the front side is on the roster, not a named player
    reported = client.put(
        f"/player-series/{first['id']}",
        headers=member("90002"),
        data={"action": "score_updated", "player1_score": "2", "player2_score": "0"},
    )

    assert reported.status_code == 200, reported.text
    # A player of a team that plays the other semifinal is refused
    stranger = client.put(
        f"/player-series/{first['id']}",
        headers=member(rosters[2][0]),
        json={"date_time": "2026-03-01 20:00:00"},
    )
    assert stranger.status_code == 403, stranger.text
    assert stranger.json() == {"error": "not_authorized_for_this_series"}


def test_the_standings_of_a_team_cup_name_the_teams(
    client: Client, auth_headers: dict[str, str], member: Callable[..., dict[str, str]]
) -> None:
    """One line per entrant, named by its team, with no user behind it."""
    event, stage, team_ids, _ = team_cup(client, auth_headers, member)
    generate(client, auth_headers, event, stage)
    for row in stage_series(client, event, stage)["series"]:
        score(client, auth_headers, row["id"], 2, 0)

    table = client.get(f"/events/{event}/stages/{stage}/standings").json()

    rows = table[0]["rows"]
    assert len(rows) == 4
    # The winner of the final leads, the side it beat is second
    assert [row["name"] for row in rows][:2] == ["T1", "T2"]
    assert {row["name"] for row in rows} == {"T1", "T2", "T3", "T4"}
    assert all(row["user_id"] is None for row in rows)
    assert {row["team_id"] for row in rows} == set(team_ids)


def test_a_solo_cup_still_writes_the_user_beside_the_entrant(
    client: Client, auth_headers: dict[str, str]
) -> None:
    """A solo entrant fills both ids, so every GNL-shaped reader still reads."""
    event, (stage,) = cup(4)
    generate(client, auth_headers, event, stage)

    rows = stage_series(client, event, stage)["series"]
    semis = [row for row in rows if row["player1_id"] is not None]

    assert len(semis) == 2
    assert all(row["entrant1_id"] and row["entrant2_id"] for row in semis)
    assert all(row["team1"] is None and row["side_size"] == 1 for row in rows)
    table = client.get(f"/events/{event}/stages/{stage}/standings").json()
    assert all(row["user_id"] is not None for row in table[0]["rows"])
