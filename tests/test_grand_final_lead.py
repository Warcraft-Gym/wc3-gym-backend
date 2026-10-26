"""A double elimination's grand final may give the upper-bracket winner a head start.

The stage names it as the `lead` modifier and the games in `grand_final_lead`:
the grand final's side 1, the upper-bracket winner, opens that many games up.
The score counts the head start, so a Bo3 that opens 1-0 ends 2-0, 2-1 or
1-2, and the games reported are the ones played. Every other series opens
0-0. A head start stays below the wins its grand final takes, so a Bo1 grand
final allows none.
"""

from typing import Any

import pytest
from httpx2 import Client
from pydantic import ValidationError

from app.models.enums import StageFormat
from app.models.event_stage import EventStageWrite
from tests.test_stage_engine import bracket, cup, generate, score


def test_a_head_start_names_its_games_and_fits_its_grand_final() -> None:
    double: dict[str, Any] = {"format": StageFormat.double_elimination}
    # Bo1 early, a Bo3 grand final opening 1-0, and a Bo5 one opening 2-0
    EventStageWrite.model_validate(
        {
            **double,
            "best_of": 1,
            "best_of_by_round": "grand_final:3",
            "grand_final_modifier": "lead",
            "grand_final_lead": 1,
        }
    )
    EventStageWrite.model_validate(
        {**double, "best_of": 5, "grand_final_modifier": "lead", "grand_final_lead": 2}
    )
    refused: list[tuple[dict[str, Any], str]] = [
        ({**double, "grand_final_modifier": "lead"}, "goes with a lead grand final"),
        ({**double, "grand_final_lead": 1}, "goes with a lead grand final"),
        (
            {
                "format": StageFormat.single_elimination,
                "grand_final_modifier": "lead",
                "grand_final_lead": 1,
            },
            "double elimination grand final",
        ),
        (
            {
                **double,
                "best_of": 3,
                "grand_final_modifier": "lead",
                "grand_final_lead": 2,
            },
            "ends at 2 wins, so the head start is 1 game at most",
        ),
        (
            {
                **double,
                "best_of": 1,
                "grand_final_modifier": "lead",
                "grand_final_lead": 1,
            },
            "needs a grand final of Bo3 or longer",
        ),
    ]
    for fields, words in refused:
        with pytest.raises(ValidationError, match=words):
            EventStageWrite.model_validate(fields)


def grand_final(client: Client, headers: dict[str, str]) -> tuple[int, dict[str, Any]]:
    """Four entrants of a Bo3 double elimination down to a grand final that the
    upper-bracket winner opens 1-0."""
    event, (stage,) = cup(
        4,
        StageFormat.double_elimination,
        best_of=3,
        grand_final_modifier="lead",
        grand_final_lead=1,
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
                assert score(client, headers, row["id"], 2, 0).status_code == 200
    final = next(row for row in bracket(stage) if row["round"] == "Grand final")
    return event, final


def test_the_grand_final_opens_with_the_head_start_and_counts_it(
    client: Client, auth_headers: dict[str, str]
) -> None:
    event, final = grand_final(client, auth_headers)
    stage = client.get(f"/events/{event}").json()["stages"][0]
    assert (stage["grand_final_modifier"], stage["grand_final_lead"]) == ("lead", 1)
    read = client.get(f"/cup-series/{final['id']}").json()
    assert read["head_start"] == 1
    # no reset is drawn, and every other series opens 0-0
    rounds = {row["round"] for row in bracket(stage["id"])}
    assert "Grand final reset" not in rounds
    upper = next(
        row for row in bracket(stage["id"]) if row["round"] == "Upper bracket final"
    )
    assert client.get(f"/cup-series/{upper['id']}").json()["head_start"] == 0

    # side 1 cannot score below its head start
    below = score(client, auth_headers, final["id"], 0, 2)
    assert below.status_code == 400, below.text
    assert "starts 1-0" in below.json()["error"]

    # a report counts the head start in the score and lists the games played
    played = [{"game_no": 1, "winner_side": "B"}, {"game_no": 2, "winner_side": "A"}]
    path = f"/cup-series/{final['id']}/report"
    too_many = client.put(
        path,
        json={
            "player1_score": 2,
            "player2_score": 1,
            "games": [*played, {"game_no": 3, "winner_side": "A"}],
        },
        headers=auth_headers,
    )
    assert too_many.status_code == 400, too_many.text
    reported = client.put(
        path,
        json={"player1_score": 2, "player2_score": 1, "games": played},
        headers=auth_headers,
    )
    assert reported.status_code == 200, reported.text
    assert (reported.json()["player1_score"], reported.json()["player2_score"]) == (
        2,
        1,
    )
    assert len(reported.json()["games"]) == 2


def test_the_lower_bracket_winner_takes_a_head_start_final_by_winning_every_game(
    client: Client, auth_headers: dict[str, str]
) -> None:
    _, final = grand_final(client, auth_headers)

    taken = score(client, auth_headers, final["id"], 1, 2)

    assert taken.status_code == 200, taken.text
    assert (taken.json()["player1_score"], taken.json()["player2_score"]) == (1, 2)
