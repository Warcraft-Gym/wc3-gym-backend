"""A season is a list of rounds, one per playday, each with a date window."""

from pathlib import Path
from typing import Any

import pytest
from httpx2 import Client
from sqlalchemy import create_engine, text
from sqlalchemy.exc import IntegrityError

from app.core.db import Session
from app.models.match import Match, MatchCreate
from app.models.relationships import round_row
from app.models.round_availability import DBRoundAvailability
from app.models.series import Series, SeriesCreate
from app.services.matches import MatchService
from app.services.series import SeriesService
from tests.migrate import downgrade_to, fresh_database, upgrade_to, upgrade_to_head
from tests.seed import add_match

# The revision before the week map became the rounds table
BEFORE_ROUNDS = "d5e8f1a2b3c4"


def rounds(body: dict[str, Any]) -> list[tuple[int, str | None, str | None]]:
    return [(r["playday"], r["start_date"], r["end_date"]) for r in body["rounds"]]


def test_a_new_season_gets_a_week_long_round_per_playday(
    client: Client, auth_headers: dict[str, str]
) -> None:
    resp = client.post(
        "/seasons",
        json={
            "name": "S2",
            "round_count": 3,
            "series_per_round": 2,
            "start_date": "2026-09-14",
        },
        headers=auth_headers,
    )

    assert resp.status_code == 201, resp.text
    assert rounds(resp.json()) == [
        (1, "2026-09-14", "2026-09-20"),
        (2, "2026-09-21", "2026-09-27"),
        (3, "2026-09-28", "2026-10-04"),
    ]


def test_a_season_without_a_start_has_undated_rounds_until_one_is_set(
    client: Client, auth_headers: dict[str, str]
) -> None:
    resp = client.post(
        "/seasons",
        json={"name": "S2", "round_count": 2, "series_per_round": 2},
        headers=auth_headers,
    )
    assert rounds(resp.json()) == [(1, None, None), (2, None, None)]

    resp = client.put(
        f"/seasons/{resp.json()['id']}",
        json={"start_date": "2026-10-05"},
        headers=auth_headers,
    )
    assert rounds(resp.json()) == [
        (1, "2026-10-05", "2026-10-11"),
        (2, "2026-10-12", "2026-10-18"),
    ]


def test_changing_the_week_count_adds_and_drops_rounds_but_moves_none(
    client: Client, seeded: dict[str, Any], auth_headers: dict[str, str]
) -> None:
    """The seeded season runs four weeks from 5 Jan 2026."""
    season_id = seeded["season_id"]
    client.put(
        f"/seasons/{season_id}/rounds",
        json={"playday": 2, "start_date": "2026-01-13", "end_date": "2026-01-14"},
        headers=auth_headers,
    )

    resp = client.put(
        f"/seasons/{season_id}", json={"round_count": 5}, headers=auth_headers
    )
    assert rounds(resp.json()) == [
        (1, "2026-01-05", "2026-01-11"),
        (2, "2026-01-13", "2026-01-14"),
        (3, "2026-01-19", "2026-01-25"),
        (4, "2026-01-26", "2026-02-01"),
        (5, "2026-02-02", "2026-02-08"),
    ]

    resp = client.put(
        f"/seasons/{season_id}", json={"round_count": 2}, headers=auth_headers
    )
    assert rounds(resp.json()) == [
        (1, "2026-01-05", "2026-01-11"),
        (2, "2026-01-13", "2026-01-14"),
    ]


def test_a_round_write_keeps_the_fields_it_leaves_out(
    client: Client, seeded: dict[str, Any], auth_headers: dict[str, str]
) -> None:
    season_id = seeded["season_id"]
    resp = client.put(
        f"/seasons/{season_id}/rounds",
        json={"playday": 1, "end_date": "2026-01-05"},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert rounds(resp.json())[0] == (1, "2026-01-05", "2026-01-05")

    # A null end date makes a one-day round
    resp = client.put(
        f"/seasons/{season_id}/rounds",
        json={"playday": 1, "end_date": None},
        headers=auth_headers,
    )
    assert rounds(resp.json())[0] == (1, "2026-01-05", None)


def test_a_round_cannot_end_before_it_starts(
    client: Client, seeded: dict[str, Any], auth_headers: dict[str, str]
) -> None:
    resp = client.put(
        f"/seasons/{seeded['season_id']}/rounds",
        json={"playday": 1, "end_date": "2026-01-04"},
        headers=auth_headers,
    )
    assert resp.status_code == 400, resp.text
    assert resp.json() == {"error": "end_date must not be before start_date"}


def test_the_migration_dates_every_round_and_keeps_the_week_maps(
    tmp_path: Path,
) -> None:
    url = fresh_database(tmp_path, "rounds")
    upgrade_to(url, BEFORE_ROUNDS)
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO seasons (id, name, number_weeks, series_per_week, start_date) "
                "VALUES (1, 'Dated', 3, 2, '2026-01-05'), (2, 'Undated', 2, 2, NULL)"
            )
        )
        connection.execute(
            text("INSERT INTO maps (id, name) VALUES (7, 'Concealed Hill')")
        )
        connection.execute(
            text(
                "INSERT INTO season_week_map (season_id, playday, map_id) "
                "VALUES (1, 2, 7)"
            )
        )

    upgrade_to_head(url)

    with engine.connect() as connection:
        rows = connection.execute(
            text(
                "SELECT season_id, number, start_date, end_date, map_id "
                "FROM event_round ORDER BY season_id, number"
            )
        ).all()
    assert [tuple(map(str, row)) for row in rows] == [
        ("1", "1", "2026-01-05", "2026-01-11", "None"),
        ("1", "2", "2026-01-12", "2026-01-18", "7"),
        ("1", "3", "2026-01-19", "2026-01-25", "None"),
        ("2", "1", "None", "None", "None"),
        ("2", "2", "None", "None", "None"),
    ]


def test_the_contract_migration_drops_the_view_and_the_date_frame(
    tmp_path: Path,
) -> None:
    from sqlalchemy import inspect

    url = fresh_database(tmp_path, "contract")
    upgrade_to_head(url)
    engine = create_engine(url)

    assert "season_week_map" not in inspect(engine).get_view_names()
    assert "date_frame" not in {
        c["name"] for c in inspect(engine).get_columns("matches")
    }
    downgrade_to(url, "e6f1a9c3d5b7")
    assert "season_week_map" in inspect(engine).get_view_names()
    assert "date_frame" in {c["name"] for c in inspect(engine).get_columns("matches")}


def test_the_round_count_follows_the_rows_not_a_stored_number(
    client: Client, auth_headers: dict[str, str]
) -> None:
    """Nothing stores the count. The round rows are the count, so deleting one
    through the season's own endpoint moves it."""
    body = client.post(
        "/seasons",
        json={"name": "Counted", "round_count": 4, "series_per_round": 2},
        headers=auth_headers,
    ).json()
    assert (body["round_count"], len(body["rounds"])) == (4, 4)

    fewer = client.put(
        f"/seasons/{body['id']}", json={"round_count": 2}, headers=auth_headers
    ).json()
    assert (fewer["round_count"], len(fewer["rounds"])) == (2, 2)

    # a change that touches neither the count nor the dates leaves the rows alone
    same = client.put(
        f"/seasons/{body['id']}", json={"name": "Renamed"}, headers=auth_headers
    ).json()
    assert (same["round_count"], len(same["rounds"])) == (2, 2)


def test_an_answer_goes_with_the_round_the_count_drops(
    client: Client, seeded: dict[str, Any], auth_headers: dict[str, str]
) -> None:
    """An answer is about one round and cascades with it, so a season that
    nobody has played can still lose a round."""
    season_id, player_id = seeded["season_id"], seeded["player_ids"][0]
    with Session.begin() as session:
        round_4 = round_row(session, season_id, 4)
        assert round_4 and round_4.id
        round_4_id = round_4.id
        session.add(
            DBRoundAvailability(
                user_id=player_id,
                season_id=season_id,
                playday=4,
                round_id=round_4.id,
                available=False,
                set_by_user_id=player_id,
            )
        )

    resp = client.put(
        f"/seasons/{season_id}", json={"round_count": 3}, headers=auth_headers
    )

    assert resp.status_code == 200, resp.text
    with Session() as session:
        assert session.get(DBRoundAvailability, (player_id, round_4_id)) is None


def test_a_round_a_match_sits_on_holds_the_count_up(
    client: Client, seeded: dict[str, Any], auth_headers: dict[str, str]
) -> None:
    """A match holds a tie and its series, so the drop is refused and named."""
    season_id = seeded["season_id"]
    with Session.begin() as session:
        add_match(
            session,
            team1_id=seeded["team_a_id"],
            team2_id=seeded["team_b_id"],
            season_id=season_id,
            playday=3,
        )

    resp = client.put(
        f"/seasons/{season_id}", json={"round_count": 2}, headers=auth_headers
    )

    assert resp.status_code == 400, resp.text
    assert resp.json() == {
        "error": "round 3 still holds matches; delete them before the count falls"
    }


def test_the_services_give_a_new_tie_and_its_series_the_round(
    seeded: dict[str, Any],
) -> None:
    """A match names the round its playday holds, and a series takes the round
    of the tie it is written into."""
    match = MatchService().add(
        MatchCreate(
            team1_id=seeded["team_a_id"],
            team2_id=seeded["team_b_id"],
            season_id=seeded["season_id"],
            playday=2,
        )
    )
    series = SeriesService().add(
        SeriesCreate(
            match_id=match.id,
            player1_id=seeded["player_ids"][0],
            player2_id=seeded["player_ids"][2],
            host_player_id=seeded["player_ids"][0],
        )
    )

    with Session() as session:
        round_2 = round_row(session, seeded["season_id"], 2)
        stored_match = session.get(Match, match.id)
        stored = session.get(Series, series.id)
        assert round_2 and stored_match and stored
        assert stored_match.round_id == round_2.id
        assert stored.round_id == round_2.id


def test_a_series_cannot_sit_in_another_round_than_its_tie(
    seeded: dict[str, Any],
) -> None:
    """The (match_id, round_id) key points at the tie and its round together,
    so a series of the round 1 tie cannot claim round 2."""
    with Session() as session, pytest.raises(IntegrityError):
        session.add(
            Series(
                match_id=seeded["match_id"],
                round_id=seeded["round_ids"][1],
                player1_id=seeded["player_ids"][0],
                player2_id=seeded["player_ids"][3],
                host_player_id=seeded["player_ids"][0],
            )
        )
        session.flush()


def test_two_players_meet_once_in_a_round_without_a_tie(
    seeded: dict[str, Any],
) -> None:
    """No team tie groups a cup series, so the round and the two players are
    the key; the same pair in another round is a different series."""

    def pair(round_id: int) -> Series:
        return Series(
            match_id=None,
            round_id=round_id,
            player1_id=seeded["player_ids"][0],
            player2_id=seeded["player_ids"][3],
            host_player_id=seeded["player_ids"][0],
        )

    with Session.begin() as session:
        session.add_all([pair(seeded["round_ids"][0]), pair(seeded["round_ids"][1])])

    with Session() as session, pytest.raises(IntegrityError):
        session.add(pair(seeded["round_ids"][0]))
        session.flush()
