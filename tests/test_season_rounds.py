"""A season is a list of rounds, one per playday, each with a date window."""

from pathlib import Path
from typing import Any

from httpx2 import Client
from sqlalchemy import create_engine, text

from tests.migrate import downgrade_to, fresh_database, upgrade_to, upgrade_to_head

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
            "number_weeks": 3,
            "series_per_week": 2,
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
        json={"name": "S2", "number_weeks": 2, "series_per_week": 2},
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
        f"/seasons/{season_id}", json={"number_weeks": 5}, headers=auth_headers
    )
    assert rounds(resp.json()) == [
        (1, "2026-01-05", "2026-01-11"),
        (2, "2026-01-13", "2026-01-14"),
        (3, "2026-01-19", "2026-01-25"),
        (4, "2026-01-26", "2026-02-01"),
        (5, "2026-02-02", "2026-02-08"),
    ]

    resp = client.put(
        f"/seasons/{season_id}", json={"number_weeks": 2}, headers=auth_headers
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
                "SELECT season_id, playday, start_date, end_date, map_id "
                "FROM season_rounds ORDER BY season_id, playday"
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
