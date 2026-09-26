"""Archive conservation, ambiguity and lifecycle checks on both supported databases."""

from copy import deepcopy
from typing import Any

import pytest
from httpx2 import Client
from sqlalchemy import func, select
from sqlmodel import col

from app.core.db import Session
from app.models.event_award import EventAward
from app.models.event_entrant import EventEntrant
from app.models.event_history import EventVideo, HistoricalParticipant, KothHistoryEvent
from app.models.series import Series
from app.models.series_game import DBSeriesGame
from app.models.user import User
from app.services.koth.history_import import bounds, import_capture, local_url
from tests.test_koth_night import open_night


def capture() -> list[dict[str, Any]]:
    def pairing(winner: str | None = None) -> dict[str, Any]:
        return {
            "record_type": "match",
            "player_1": "short",
            "player_2": "other",
            "winner": winner,
            "raw_text": "short vs other (offrace)",
            "raw_html": "<li>short vs other (offrace)</li>",
        }

    return [
        {
            "event_id": "capture-first",
            "date": None,
            "date_text": "November 31, 2024",
            "source_url": "https://example.com/history/",
            "sections": [
                {
                    "kind": "bracket",
                    "title": "1500 to ~1700 MMR",
                    "matches": [pairing(), pairing("other")],
                    "crowns": [
                        {"player": "OTHER", "raw_text": "OTHER is crowned King"}
                    ],
                },
                {
                    "kind": "bracket",
                    "title": "Gold and below",
                    "matches": [pairing()],
                    "crowns": [],
                },
                {
                    "kind": "exhibition",
                    "title": "Random games",
                    "matches": [pairing()],
                    "crowns": [],
                },
            ],
            "videos": [{"video_id": "abcdefghijk", "title": "Featured game"}],
        }
    ]


def counts() -> tuple[int, ...]:
    with Session() as session:
        return tuple(
            session.scalar(select(func.count()).select_from(model)) or 0
            for model in (KothHistoryEvent, Series, DBSeriesGame, EventVideo)
        )


def test_import_keeps_unknowns_and_every_competitive_bo1(client: Client) -> None:
    dry = import_capture(capture())
    assert counts() == (0, 0, 0, 0)
    assert dry["counts"]["excluded_rows"] == 1
    result = import_capture(capture(), apply=True)
    event_id = result["event_ids"]["capture-first"]
    assert counts() == (1, 3, 3, 1)
    with Session() as session:
        assert session.scalar(select(func.count()).select_from(User)) == 0
        people = list(session.scalars(select(HistoricalParticipant)))
        assert [p.source_name for p in people].count("short") == 2
        assert (
            len(people) == 5
        )  # the crown's spelling is a separate unresolved identity
        assert all(
            row.race is None and row.user_id is None
            for row in session.scalars(select(EventEntrant))
        )
        games = list(
            session.scalars(select(DBSeriesGame).order_by(col(DBSeriesGame.series_id)))
        )
        assert [g.winner_side for g in games] == [None, "B", None]
        assert all(g.game_no == 1 and g.map_id is None for g in games)
        assert session.scalars(select(EventAward)).one().awarded_at is None
    response = client.get(f"/koth/nights/{event_id}/board")
    assert response.status_code == 200, response.text
    board = response.json()
    assert board["historical"] and board["closed"]
    assert board["starts_at"] is None
    assert board["date_label"] == "November 31, 2024"
    assert board["series_count"] == 3
    first, second = board["brackets"]
    assert (first["name"], first["lower_bound"], first["upper_bound"]) == (
        "1500 to ~1700 MMR",
        1500,
        1700,
    )
    assert second["name"] == "Gold and below" and second["lower_bound"] is None
    assert first["historical_king"]["name"] == "OTHER"
    assert [r["winner_side"] for r in first["history"]] == [None, 2]
    for bracket in board["brackets"]:
        assert not bracket["queue"] and bracket["open_series"] is None
        for row in bracket["history"]:
            assert row["side1"]["race"] is None and row["side1"]["user_id"] is None
    assert board["videos"][0]["url"] == "https://www.youtube.com/watch?v=abcdefghijk"
    assert "source_record" not in response.text and "raw_html" not in response.text
    assert int(response.headers["X-DB-Statements"]) <= 6
    assert "s-maxage=15" in response.headers["cache-control"]
    series = client.get(f"/events/{event_id}/series")
    assert series.status_code == 200, series.text
    assert len(series.json()) == 3
    assert series.json()[0]["player1_source_name"] == "short"
    assert series.json()[0]["result_unavailable"]
    from app.services.series import SeriesService

    assert SeriesService().count(None, season_id=event_id) == 3
    detail = client.get(f"/events/{event_id}").json()
    assert detail["phase"] == "finished"


def test_rerun_and_resume_preserve_existing_rows(client: Client) -> None:
    first = import_capture(capture(), apply=True)
    second = import_capture(capture(), apply=True)
    assert second["inserted_events"] == 0 and second["event_ids"] == first["event_ids"]
    extra = deepcopy(capture()[0])
    extra["event_id"] = "capture-second"
    result = import_capture(capture() + [extra], apply=True)
    assert result["inserted_events"] == 1 and counts() == (2, 6, 6, 2)


def test_source_drift_and_bad_batch_fail_before_any_new_event(client: Client) -> None:
    import_capture(capture(), apply=True)
    changed = capture()
    changed[0]["sections"][0]["title"] = "1600+"
    extra = deepcopy(changed[0])
    extra["event_id"] = "new-first"
    with pytest.raises(ValueError, match="Source drift"):
        import_capture([extra] + changed, apply=True)
    assert counts() == (1, 3, 3, 1)
    extra["sections"][0]["matches"][0]["player_1"] = None
    with pytest.raises(ValueError, match="Unresolved side"):
        import_capture([extra], apply=True)
    assert counts() == (1, 3, 3, 1)


def test_archive_cannot_be_reclosed_or_run_live(
    client: Client, auth_headers: dict[str, str]
) -> None:
    event_id = import_capture(capture(), apply=True)["event_ids"]["capture-first"]
    before = counts()
    closed = client.post(f"/koth/nights/{event_id}/close", headers=auth_headers)
    assert closed.status_code == 400
    with Session() as session:
        series = session.scalars(select(Series)).first()
        assert series is not None
        series_id = series.id
    changed = client.put(
        f"/koth/nights/{event_id}/series/{series_id}/result",
        json={"winner": 1},
        headers=auth_headers,
    )
    assert changed.status_code == 400
    patched = client.put(
        f"/series/{series_id}",
        json={"player1_score": 1, "player2_score": 0},
        headers=auth_headers,
    )
    assert patched.status_code == 400
    assert counts() == before
    assert client.get(f"/events/{event_id}").json()["archived"] is True
    with Session() as session:
        assert len(list(session.scalars(select(EventAward)))) == 1


def test_import_does_not_treat_unmapped_existing_events_as_duplicates(
    client: Client, auth_headers: dict[str, str]
) -> None:
    open_night(client, auth_headers)
    with pytest.raises(ValueError, match="source mappings"):
        import_capture(capture(), apply=True)
    assert counts() == (0, 0, 0, 0)


@pytest.mark.parametrize(
    ("label", "expected"),
    [
        ("Gold and below", (None, None)),
        ("Platinum to 1700 MMR", (None, 1700)),
        ("1450 and Below", (None, 1450)),
        ("2000+ Games", (2000, None)),
        ("1600 to the mooon", (1600, None)),
        ("1500 to ~1700 MMR", (1500, 1700)),
    ],
)
def test_source_bounds(label: str, expected: tuple[int | None, int | None]) -> None:
    assert bounds(label) == expected


@pytest.mark.parametrize(
    "url",
    [
        "postgresql+psycopg://remote.invalid/db",
        "postgresql+psycopg://localhost/db?host=remote.invalid",
        "sqlite:///file",
        "postgresql+psycopg://localhost/db",
    ],
)
def test_cli_refuses_nonlocal_targets(url: str) -> None:
    with pytest.raises(ValueError, match="loopback"):
        local_url(url)


def test_cli_refuses_a_libpq_host_override(monkeypatch: pytest.MonkeyPatch) -> None:
    url = "postgresql+psycopg://127.0.0.1/db"
    assert local_url(url) == url
    monkeypatch.setenv("PGHOSTADDR", "192.0.2.1")
    with pytest.raises(ValueError, match="loopback"):
        local_url(url)


def test_full_offline_capture(client: Client) -> None:
    """Opt-in conservation test; source files stay outside the repository."""
    import os
    from pathlib import Path

    from app.services.koth.history_import import load_capture

    path = os.getenv("KOTH_CAPTURE_DIR")
    if not path:
        pytest.skip("Set KOTH_CAPTURE_DIR to test the offline capture")
    records = load_capture(Path(path))
    report = import_capture(records, apply=True)
    assert report["counts"]["events"] == 168
    assert report["counts"]["series"] == 1937
    assert report["counts"]["divisions"] == 444
    assert report["counts"]["videos"] == 33
    assert report["counts"]["excluded_rows"] == 136
    assert counts() == (168, 1937, 1937, 33)
    assert import_capture(records, apply=True)["inserted_events"] == 0
    for event in records:
        event_id = report["event_ids"][event["event_id"]]
        response = client.get(f"/koth/nights/{event_id}/board")
        assert response.status_code == 200, response.text
        board = response.json()
        sections = [
            section for section in event["sections"] if section["kind"] == "bracket"
        ]
        series_ids = set()
        for bracket, section in zip(board["brackets"], sections, strict=True):
            assert bracket["name"] == section["title"]
            assert bracket["open_series"] is None and not bracket["queue"]
            matches = [
                row for row in section["matches"] if row["record_type"] == "match"
            ]
            for row, source in zip(bracket["history"], matches, strict=True):
                assert row["side1"]["name"] == source["player_1"]
                assert row["side2"]["name"] == source["player_2"]
                assert row["side1"]["race"] is None and row["side2"]["race"] is None
                assert (
                    row["side1"]["user_id"] is None and row["side2"]["user_id"] is None
                )
                assert row["result_unavailable"] == (source["winner"] is None)
                winner = (
                    None
                    if source["winner"] is None
                    else 1
                    if source["winner"] == source["player_1"]
                    else 2
                )
                assert row["winner_side"] == winner
                series_ids.add(row["series_id"])
                with Session() as session:
                    game = session.get(DBSeriesGame, (row["series_id"], 1))
                    assert game is not None and game.map_id is None
                    assert game.winner_side == {1: "A", 2: "B"}.get(winner)
            crown = section["crowns"][-1]["player"] if section["crowns"] else None
            assert (
                bracket["historical_king"]["name"]
                if bracket["historical_king"]
                else None
            ) == crown
        assert board["series_count"] == len(series_ids)
        assert [video["url"] for video in board["videos"]] == [
            video["url"] for video in event["videos"]
        ]
        series = client.get(f"/events/{event_id}/series?limit=500")
        assert series.status_code == 200, series.text
        assert {row["id"] for row in series.json()} == series_ids
        assert int(response.headers["X-DB-Statements"]) <= 5
        assert int(response.headers["X-DB-Rows"]) <= 69
        assert len(response.content) < 10000
