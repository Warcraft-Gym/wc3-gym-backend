"""What an event pays when it closes: one award per place of its last stage.

Every test drives the routes an admin drives, so the award list reads the way
the event page and a player's shelf read it.
"""

from typing import Any

from httpx2 import Client
from sqlalchemy import select
from sqlmodel import col

from app.core.db import Session
from app.models.enums import StageFormat
from app.models.event_award import EventAward
from app.models.series import Series
from tests.test_koth_night import enrol, open_night, sign_up
from tests.test_stage_engine import bracket, cup, generate, score, stage_series


def finish(client: Client, headers: dict[str, str], event: int) -> list[dict[str, Any]]:
    response = client.post(f"/events/{event}/finish", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def play_out(client: Client, headers: dict[str, str], stage: int) -> None:
    """Settle every series of the stage, the first side taking each one."""
    while pending := [row for row in bracket(stage) if row["score"] == (None, None)]:
        for row in pending:
            assert score(client, headers, row["id"], 2, 0).status_code == 200


def awarded(event: int) -> list[tuple[int | None, int | None, str]]:
    """Every award row of the event, as (user, place, title)."""
    with Session.begin() as session:
        return [
            (row.user_id, row.place, row.title)
            for row in session.scalars(
                select(EventAward)
                .where(col(EventAward.event_id) == event)
                .order_by(col(EventAward.id))
            )
        ]


def test_a_finished_cup_awards_a_champion_and_a_runner_up_per_division(
    client: Client, auth_headers: dict[str, str]
) -> None:
    """Two divisions of four run in parallel, so each pays its own four places."""
    event, (stage,) = cup(4, divisions=2)
    generate(client, auth_headers, event, stage)
    play_out(client, auth_headers, stage)
    finals = [row for row in bracket(stage) if row["round"] == "Final"]

    rows = finish(client, auth_headers, event)

    assert [(row["place"], row["title"]) for row in rows] == [
        (1, "Champion"),
        (2, "Runner-up"),
        (3, "Third"),
        (4, "Placed 4"),
    ] * 2
    champions = [row["user_id"] for row in rows if row["place"] == 1]
    seconds = [row["user_id"] for row in rows if row["place"] == 2]
    assert sorted(champions) == sorted(final["sides"][0] for final in finals)
    assert sorted(seconds) == sorted(final["sides"][1] for final in finals)


def test_a_second_finish_rewrites_the_places_and_doubles_nothing(
    client: Client, auth_headers: dict[str, str]
) -> None:
    """The close is the whole list, so it can run after a score is corrected."""
    event, (stage,) = cup(4)
    generate(client, auth_headers, event, stage)
    play_out(client, auth_headers, stage)
    first = finish(client, auth_headers, event)

    second = finish(client, auth_headers, event)

    assert len(awarded(event)) == 4
    assert [(row["user_id"], row["place"]) for row in second] == [
        (row["user_id"], row["place"]) for row in first
    ]
    assert [row["title"] for row in second] == [row["title"] for row in first]


def test_closing_a_koth_night_crowns_the_king_of_every_bracket(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    """The table puts the last winner on the throne, so he takes place one."""
    night = open_night(client, auth_headers)
    for tag, mmr in (("King#1", 1300), ("Rival#2", 1400)):
        enrol(tag, mmr)
        sign_up(client, tag, tag.split("#")[0], "human")
    row = stage_series(client, night["id"], night["stages"][0]["id"])["series"][0]
    # The rival seeds first, so the second side takes the throne
    assert score(client, auth_headers, row["id"], 0, 1).status_code == 200

    closed = client.post(f"/koth/nights/{night['id']}/close", headers=auth_headers)

    assert closed.status_code == 200, closed.text
    places = awarded(night["id"])
    assert [(place, title) for _, place, title in places] == [
        (1, "Champion"),
        (2, "Runner-up"),
    ]
    assert places[0][0] == row["player2_id"]


def test_a_cup_win_stands_beside_a_season_championship(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    """One player wins the seeded season with Alpha and a cup of his own."""
    with Session.begin() as session:
        series = session.get(Series, seeded["series_open_id"])
        assert series is not None
        series.player1_score, series.player2_score = 2, 0
    player = seeded["player_ids"][0]
    event, (stage,) = cup(
        2, StageFormat.round_robin, ids=[player, seeded["player_ids"][2]]
    )
    generate(client, auth_headers, event, stage)
    play_out(client, auth_headers, stage)
    finish(client, auth_headers, event)

    trophies = client.get(f"/users/{player}").json()["trophies"]

    assert [row["title"] for row in trophies] == [
        "Autumn Cup Champion",
        "Season 1 Champion",
    ]
    assert trophies[0]["season_id"] == event
    assert trophies[1]["team_name"] == "Alpha"
    # The beaten entrant takes no trophy from the cup
    assert client.get(f"/users/{seeded['player_ids'][2]}").json()["trophies"] == []
