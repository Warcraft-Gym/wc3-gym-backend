"""A drawn cup can be taken back and drawn anew, and a player who has not
played yet can be swapped for another in the same place of the bracket.

Taking the draw back deletes the stage's rounds, and with them every series,
result, veto and replay; the entrants stay and the seeds open again.
"""

from typing import Any

from httpx2 import Client
from sqlmodel import col, select

from app.core.db import Session
from app.models.event_entrant import EventEntrant
from app.models.event_stage import EventStage
from app.models.relationships import DBEventRound
from app.models.series import Series
from app.models.series_veto_step import DBSeriesVetoStep
from tests.test_cup_best_of import maps
from tests.test_event_organizers import Headers, Member, create, draw, enter, grant
from tests.test_stage_engine import players

DOUBLE = [{"format": "double_elimination", "best_of": 1}]


def entrants(event: int) -> dict[int, EventEntrant]:
    """The entrants of the event by user id."""
    with Session.begin() as session:
        rows = session.scalars(
            select(EventEntrant).where(col(EventEntrant.event_id) == event)
        ).all()
        session.expunge_all()
        return {row.user_id: row for row in rows if row.user_id is not None}


def series_of(event: int) -> list[Series]:
    with Session.begin() as session:
        rows = session.scalars(
            select(Series)
            .join(DBEventRound, col(DBEventRound.id) == col(Series.round_id))
            .where(col(DBEventRound.season_id) == event)
            .order_by(col(Series.id))
        ).all()
        session.expunge_all()
        return list(rows)


def veto_step(series_id: int | None) -> None:
    assert series_id is not None
    with Session.begin() as session:
        session.add(
            DBSeriesVetoStep(
                series_id=series_id,
                step_no=1,
                side="A",
                action="ban",
                map_id=maps(1)[0],
            )
        )


def walkover(client: Client, headers: Headers, series_id: int | None) -> None:
    assert series_id is not None
    response = client.put(
        f"/series/{series_id}/result-kind",
        json={"result_kind": "walkover", "winner": 1},
        headers=headers,
    )
    assert response.status_code == 200, response.text


def undraw(client: Client, headers: Headers, event: dict[str, Any]) -> Any:  # noqa: ANN401
    return client.delete(
        f"/events/{event['id']}/stages/{event['stages'][0]['id']}/series",
        headers=headers,
    )


def test_the_draw_is_taken_back_with_every_series_and_drawn_anew(
    client: Client, auth_headers: Headers
) -> None:
    event = create(client, auth_headers)
    ids = players(9)
    enter(client, auth_headers, event["id"], ids[:8])
    stage = event["stages"][0]["id"]
    assert draw(client, auth_headers, event).status_code == 200
    locked = client.post(
        f"/events/{event['id']}/stages/{stage}/seeds/lock", headers=auth_headers
    )
    assert locked.status_code == 200, locked.text
    drawn = series_of(event["id"])
    walkover(client, auth_headers, drawn[0].id)
    veto_step(drawn[1].id)

    taken = undraw(client, auth_headers, event)
    assert taken.status_code == 200, taken.text
    assert taken.json() == {"series": len(drawn), "results": 1}
    assert series_of(event["id"]) == []
    with Session.begin() as session:
        assert not session.scalars(
            select(DBEventRound).where(col(DBEventRound.season_id) == event["id"])
        ).all()
        assert not session.scalars(select(DBSeriesVetoStep)).all()
        stage_row = session.get(EventStage, stage)
        assert stage_row is not None
        assert stage_row.seeds_locked_at is None

    # one more player, seeded again, drawn again
    enter(client, auth_headers, event["id"], ids[8:])
    assert draw(client, auth_headers, event).status_code == 200
    # nine players: one play-in, four quarterfinals, two semifinals, the final
    assert len(series_of(event["id"])) == 8


def test_a_draw_stays_where_there_is_nothing_to_take_back(
    client: Client, auth_headers: Headers, member: Member
) -> None:
    event = create(client, auth_headers)
    assert undraw(client, auth_headers, event).status_code == 400

    enter(client, auth_headers, event["id"], players(2))
    assert draw(client, auth_headers, event).status_code == 200
    # an organizer of another cup runs nothing of this one
    grant(client, auth_headers, "81")
    assert undraw(client, member("81"), event).status_code == 403

    walkover(client, auth_headers, series_of(event["id"])[0].id)
    finished = client.post(f"/events/{event['id']}/finish", headers=auth_headers)
    assert finished.status_code == 200, finished.text
    refused = undraw(client, auth_headers, event)
    assert refused.status_code == 400
    assert "reopen" in refused.text


def test_a_swap_puts_the_new_player_in_every_series_of_the_old_one(
    client: Client, auth_headers: Headers
) -> None:
    """Three players in a double elimination: the top seed walks over the
    padded side into the upper final, and the new player takes both."""
    event = create(client, auth_headers, stages=DOUBLE)
    ids = players(4)
    enter(client, auth_headers, event["id"], ids[:3])
    assert draw(client, auth_headers, event).status_code == 200
    top = next(row for row in entrants(event["id"]).values() if row.seed == 1)
    named = [
        row.id
        for row in series_of(event["id"])
        if top.id in (row.entrant1_id, row.entrant2_id)
    ]
    assert len(named) >= 2

    late = ids[3]
    swapped = client.post(
        f"/events/{event['id']}/entrants/{top.id}/replace",
        json={"user_id": late, "race": "HU"},
        headers=auth_headers,
    )
    assert swapped.status_code == 200, swapped.text
    rows = entrants(event["id"])
    assert top.user_id not in rows
    assert rows[late].seed == 1
    by_id = {row.id: row for row in series_of(event["id"])}
    for series_id in named:
        row = by_id[series_id]
        assert rows[late].id in (row.entrant1_id, row.entrant2_id)
        assert late in (row.player1_id, row.player2_id)


def test_a_swap_starts_the_veto_over_and_never_takes_a_played_place(
    client: Client, auth_headers: Headers
) -> None:
    event = create(client, auth_headers)
    first, second, late, other = players(4)
    enter(client, auth_headers, event["id"], [first, second])
    assert draw(client, auth_headers, event).status_code == 200
    (only,) = series_of(event["id"])
    veto_step(only.id)
    leaving = entrants(event["id"])[first]

    # a player already in the cup cannot come in again
    refused = client.post(
        f"/events/{event['id']}/entrants/{leaving.id}/replace",
        json={"user_id": second, "race": "HU"},
        headers=auth_headers,
    )
    assert refused.status_code == 400
    assert "already signed up" in refused.text

    swapped = client.post(
        f"/events/{event['id']}/entrants/{leaving.id}/replace",
        json={"user_id": late, "race": "HU"},
        headers=auth_headers,
    )
    assert swapped.status_code == 200, swapped.text
    with Session.begin() as session:
        assert not session.scalars(select(DBSeriesVetoStep)).all()

    walkover(client, auth_headers, only.id)
    played = entrants(event["id"])[late]
    refused = client.post(
        f"/events/{event['id']}/entrants/{played.id}/replace",
        json={"user_id": other, "race": "HU"},
        headers=auth_headers,
    )
    assert refused.status_code == 400
    assert "played a match" in refused.text
