"""A Swiss cup draws each round itself once the round before has every result,
stops at the rounds it names, and may end in a playoff drawn the moment the
Swiss rounds end; every entrant takes a place."""

from typing import Any

from httpx2 import Client

from app.models.enums import SchedulingMode, StageFormat
from tests.test_awards import finish
from tests.test_stage_engine import bracket, cup, generate, score


def draw_round(client: Client, headers: dict[str, str], event: int, stage: int) -> Any:  # noqa: ANN401
    return client.post(f"/events/{event}/stages/{stage}/rounds", headers=headers)


def open_series(stage: int) -> list[dict[str, Any]]:
    return [
        row
        for row in bracket(stage)
        if row["score"] == (None, None) and None not in row["sides"]
    ]


def play_round(
    client: Client, headers: dict[str, str], stage: int, wins: int = 1
) -> int:
    """Score every open series of the stage, the first side winning; answers how many."""
    rows = open_series(stage)
    for row in rows:
        assert score(client, headers, row["id"], wins, 0).status_code == 200
    return len(rows)


def rounds_of(stage: int) -> list[str]:
    seen: list[str] = []
    for row in bracket(stage):
        if row["round"] not in seen:
            seen.append(row["round"])
    return seen


def test_a_swiss_cup_draws_its_rounds_itself_then_its_playoff(
    client: Client, auth_headers: dict[str, str]
) -> None:
    event, (swiss, playoff) = cup(
        8,
        StageFormat.swiss,
        stages=2,
        swiss_rounds=3,
        best_of=1,
        scheduling_mode=SchedulingMode.immediate,
        auto_advance=True,
        advance_count=4,
    )
    drawn = draw_round(client, auth_headers, event, swiss)
    assert drawn.status_code == 200, drawn.text
    for expected in (1, 2, 3):
        assert len(rounds_of(swiss)) == expected
        assert play_round(client, auth_headers, swiss) == 4
    # three rounds and no fourth; the top four play the playoff, drawn at once
    assert len(rounds_of(swiss)) == 3
    assert open_series(swiss) == []
    assert len(open_series(playoff)) == 2
    while play_round(client, auth_headers, playoff, wins=2):
        pass
    places = sorted(award["place"] for award in finish(client, auth_headers, event))
    assert places == list(range(1, 9))


def test_a_swiss_stage_plays_no_more_rounds_than_its_field_holds(
    client: Client, auth_headers: dict[str, str]
) -> None:
    event, (swiss,) = cup(
        4,
        StageFormat.swiss,
        swiss_rounds=10,
        best_of=1,
        scheduling_mode=SchedulingMode.immediate,
    )
    assert draw_round(client, auth_headers, event, swiss).status_code == 200
    while play_round(client, auth_headers, swiss):
        pass
    assert len(rounds_of(swiss)) == 3
    refused = draw_round(client, auth_headers, event, swiss)
    assert refused.status_code == 400
    assert "3 rounds" in refused.text


def test_a_result_stays_once_the_next_round_is_drawn_from_it(
    client: Client, auth_headers: dict[str, str]
) -> None:
    event, (swiss,) = cup(
        4,
        StageFormat.swiss,
        swiss_rounds=3,
        best_of=1,
        scheduling_mode=SchedulingMode.immediate,
    )
    assert draw_round(client, auth_headers, event, swiss).status_code == 200
    first = open_series(swiss)[0]
    play_round(client, auth_headers, swiss)
    assert len(rounds_of(swiss)) == 2
    changed = score(client, auth_headers, first["id"], 0, 1)
    assert changed.status_code == 400
    assert "next round" in changed.text


def test_everyone_plays_everyone_then_the_top_four_play_off(
    client: Client, auth_headers: dict[str, str]
) -> None:
    event, (league, playoff) = cup(
        5,
        StageFormat.round_robin,
        stages=2,
        best_of=1,
        scheduling_mode=SchedulingMode.immediate,
        auto_advance=True,
        advance_count=4,
    )
    generate(client, auth_headers, event, league)
    # five players, five rounds, a bye each round
    assert len(rounds_of(league)) == 5
    while play_round(client, auth_headers, league):
        pass
    assert len(open_series(playoff)) == 2
    while play_round(client, auth_headers, playoff, wins=2):
        pass
    places = sorted(award["place"] for award in finish(client, auth_headers, event))
    assert places == [1, 2, 3, 4, 5]
