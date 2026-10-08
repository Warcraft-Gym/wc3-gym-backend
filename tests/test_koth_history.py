"""Archive conservation, ambiguity and lifecycle checks on both supported databases."""

import json
from copy import deepcopy
from datetime import date
from typing import Any

import pytest
from httpx2 import Client
from sqlalchemy import func, select
from sqlmodel import col

from app.core.db import Session
from app.models.enums import Race
from app.models.event_award import EventAward
from app.models.event_division import EventDivision
from app.models.event_entrant import EventEntrant
from app.models.event_history import (
    EventVideo,
    HistoricalParticipant,
    KothHistoryEvent,
    KothHistorySeries,
)
from app.models.relationships import DBEventRound
from app.models.season import Season
from app.models.series import Series
from app.models.series_game import DBSeriesGame
from app.models.types import utcnow
from app.models.user import User
from app.services.koth.history_import import (
    LEFT,
    bounds,
    digest,
    fold,
    import_capture,
    infer_winners,
    link_players,
    local_url,
    record_days,
)
from tests.seed import active
from tests.test_koth_live import bracket_ids, place, play
from tests.test_koth_night import NIGHT, open_night


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
            "source_order": 1,
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
        assert len(people) == 4  # the crown's spelling folds into its player
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
    assert [r["inferred_winner_side"] for r in first["history"]] == [None, None]
    assert first["history"][0]["review_note"] == (
        "These two played again next, so the order does not show who won"
    )
    assert second["history"][0]["review_note"] == (
        "The old page names no king for this bracket"
    )
    for bracket in board["brackets"]:
        assert not bracket["queue"] and bracket["open_series"] is None
        for row in bracket["history"]:
            assert row["side1"]["race"] is None and row["side1"]["user_id"] is None
    assert board["videos"][0]["url"] == "https://www.youtube.com/watch?v=abcdefghijk"
    assert "source_record" not in response.text and "raw_html" not in response.text
    assert int(response.headers["X-DB-Statements"]) <= 6
    assert (
        response.headers["cache-control"]
        == "public, s-maxage=3600, stale-while-revalidate=86400"
    )
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
    reopened = client.post(f"/events/{event_id}/reopen", headers=auth_headers)
    assert reopened.status_code == 400
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
    archive = client.get(f"/events/{event_id}").json()
    assert archive["archived"] is True
    assert archive["closed_at"] is not None
    with Session() as session:
        assert len(list(session.scalars(select(EventAward)))) == 1


def test_import_does_not_treat_unmapped_existing_events_as_duplicates(
    client: Client, auth_headers: dict[str, str]
) -> None:
    open_night(client, auth_headers)
    with pytest.raises(ValueError, match="source mappings"):
        import_capture(capture(), apply=True)
    assert counts() == (0, 0, 0, 0)


def test_archived_nights_filter_the_lists_and_stay_off_the_live_reads(
    client: Client, auth_headers: dict[str, str]
) -> None:
    """The archive filter keeps or drops the imported night; live reads drop it."""
    archived = import_capture(capture(), apply=True)["event_ids"]["capture-first"]
    native = open_night(client, auth_headers)["id"]
    league = client.get(f"/events/{native}").json()["league_id"]

    def listed(path: str) -> tuple[set[int], str | None]:
        resp = client.get(path, headers=auth_headers)
        assert resp.status_code == 200, resp.text
        return {row["id"] for row in resp.json()}, resp.headers.get("X-Total-Count")

    assert listed("/events") == ({archived, native}, "2")
    assert listed("/events?archived=false") == ({native}, "1")
    assert listed("/events?archived=true") == ({archived}, "1")

    def runs(query: str = "") -> set[int]:
        body = client.get(f"/leagues/{league}{query}", headers=auth_headers).json()
        return {event["id"] for event in body["events"]}

    assert runs() == {archived, native}
    assert runs("?archived=false") == {native}
    assert runs("?archived=true") == {archived}

    mine = client.get("/me/events", headers=auth_headers)
    assert mine.status_code == 200, mine.text
    assert native in {row["id"] for row in mine.json()}
    assert archived not in {row["id"] for row in mine.json()}
    assert [row["id"] for row in client.get("/koth/events").json()] == [native]


def test_a_yearless_night_takes_its_year_from_the_page_order(client: Client) -> None:
    """Only a month and a day between two dated nights of one page get a date."""

    def night(key: str, order: int, day: str | None, label: str) -> dict[str, Any]:
        record = deepcopy(capture()[0])
        record.update(event_id=key, source_order=order, date=day, date_text=label)
        return record

    records = [
        night("newer", 1, "2022-03-06", "March 6, 2022"),
        night("between", 2, None, "February 26"),
        night("unparsed", 3, None, "November 31, 2024"),
        night("older", 4, "2021-10-23", "October 23, 2021"),
        night("last", 5, None, "October 16"),
    ]
    wide = [
        night("wide-newer", 1, "2022-12-31", "December 31, 2022"),
        night("wide-between", 2, None, "June 1"),
        night("wide-older", 3, "2020-01-01", "January 1, 2020"),
    ]
    for record in wide:
        record["source_url"] = "https://example.com/other/"
    records += wide
    untouched = deepcopy(records)
    days = record_days(records)
    assert days["between"] == date(2022, 2, 26)
    assert days["unparsed"] is None and days["last"] is None
    assert days["wide-between"] is None  # two years fit
    assert days["newer"] == date(2022, 3, 6)

    result = import_capture(records, apply=True)
    assert records == untouched
    ids = result["event_ids"]
    with Session() as session:
        event = session.get(Season, ids["between"])
        assert event is not None
        assert event.name == "KOTH February 26, 2022"
        assert event.start_date == event.end_date == date(2022, 2, 26)
        round_ = session.scalars(
            select(DBEventRound).where(col(DBEventRound.season_id) == ids["between"])
        ).one()
        assert round_.start_date == round_.end_date == date(2022, 2, 26)
        for key, name in (
            ("unparsed", "KOTH November 31, 2024"),
            ("last", "KOTH October 16"),
            ("newer", "KOTH March 6, 2022"),
        ):
            other = session.get(Season, ids[key])
            assert other is not None and other.name == name
            assert (other.start_date is None) == (key != "newer")
        archive = session.get(KothHistoryEvent, ids["between"])
        assert archive is not None
        assert archive.date_label == "February 26"
        assert archive.source_digest == digest(untouched[1])
        assert archive.source_record == untouched[1]
    assert import_capture(records, apply=True)["inserted_events"] == 0


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
    with Session() as session:
        starts = {
            event.id: event.start_date for event in session.scalars(select(Season))
        }
    read = sorted(
        str(starts[report["event_ids"][record["event_id"]]])
        for record in records
        if record["date"] is None
    )
    assert read == [
        "2021-11-06",
        "2021-11-13",
        "2021-11-20",
        "2021-11-27",
        "2021-12-18",
        "2022-01-08",
        "2022-01-15",
        "2022-02-05",
        "2022-02-12",
        "2022-02-26",
        "None",
    ]
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
            marks = [
                (bool(row["winner_side"] or row["inferred_winner_side"]), row["throne"])
                for row in bracket["history"]
            ]
            assert all(won == (throne != "none") for won, throne in marks)
            assert [throne for won, throne in marks if won][:1] in ([], ["moved"])
            # a winner who left is the source's, never read from the order
            assert all(
                row["inferred_winner_side"] is None and row["review_note"] is None
                for row in bracket["history"]
                if row["winner_left"]
            )
            for row, source in zip(bracket["history"], matches, strict=True):
                assert fold(row["side1"]["name"]) == fold(source["player_1"])
                assert fold(row["side2"]["name"]) == fold(source["player_2"])
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
        assert int(response.headers["X-DB-Statements"]) <= 6
        assert int(response.headers["X-DB-Rows"]) <= 98
        assert len(response.content) < 12000


def bo1(
    first: str, second: str, raw: str = "", winner: str | None = None
) -> dict[str, Any]:
    return {
        "record_type": "match",
        "player_1": first,
        "player_2": second,
        "winner": winner,
        "raw_text": f"{first} vs. {second} {raw}",
    }


def test_winner_stays_on_infers_a_whole_bracket() -> None:
    rows = [bo1("Ann", "Bo"), bo1("ann", "Cy", "(HU)"), bo1("Cy", "Di")]
    assert infer_winners(rows, "Di") == [(1, None), (2, None), (2, None)]
    # a source result stays the source's and is never inferred over
    assert infer_winners([], "Di") == []
    rows[1]["winner"] = "Cy"
    assert infer_winners(rows, "Di") == [(1, None), (None, None), (2, None)]


def test_a_rematch_leaves_only_its_own_row_unknown() -> None:
    rows = [bo1("Ann", "Bo"), bo1("Ann", "Cy"), bo1("Cy", "Ann"), bo1("Cy", "Di")]
    assert infer_winners(rows, "Di") == [
        (1, None),
        (None, "These two played again next, so the order does not show who won"),
        (1, None),
        (2, None),
    ]


def test_a_break_has_no_winner_and_the_order_restarts() -> None:
    rows = [bo1("Ann", "Bo"), bo1("Ann", "Cy"), bo1("Di", "Ed"), bo1("Di", "Fay")]
    assert infer_winners(rows, "Fay") == [
        (1, None),
        (None, LEFT),
        (1, None),
        (2, None),
    ]


def test_a_written_winner_who_does_not_play_on_left() -> None:
    rows = [bo1("Ann", "Bo"), bo1("Ann", "Cy", winner="Cy"), bo1("Ann", "Di")]
    assert infer_winners(rows, "Di") == [(1, None), (None, LEFT), (2, None)]


def test_a_hand_note_shows_the_source_words() -> None:
    rows = [bo1("Ann", "Bo", "(HU) (Ann had to leave) (afk)"), bo1("Bo", "Cy")]
    assert infer_winners(rows, "Cy") == [
        (None, "The old page notes: Ann had to leave; afk"),
        (2, None),
    ]


def test_a_bracket_without_a_king_leaves_the_last_row_unknown() -> None:
    rows = [bo1("Ann", "Bo"), bo1("Ann", "Cy")]
    assert infer_winners(rows, None) == [
        (1, None),
        (None, "The old page names no king for this bracket"),
    ]


def test_a_king_outside_the_last_row_leaves_it_unknown() -> None:
    rows = [bo1("Ann", "Bo"), bo1("Ann", "Cy")]
    assert infer_winners(rows, "Bo") == [
        (1, None),
        (None, "The crowned player is not in the last series"),
    ]


def test_a_name_close_to_one_in_the_next_row_is_no_break() -> None:
    rows = [bo1("Regitheth", "Bo"), bo1("Regitheht", "Cy")]
    near = "A name here is close to one in the next series; it may be the same player"
    assert infer_winners(rows, "Cy") == [(None, near), (2, None)]


def test_an_inferred_winner_shows_on_the_board_and_stays_out_of_records(
    client: Client,
) -> None:
    record = capture()[0]
    record["sections"] = [
        {
            "kind": "bracket",
            "title": "Gold and below",
            "matches": [bo1("Ann", "Bo"), bo1("Ann", "Cy"), bo1("Di", "Ed")],
            "crowns": [{"player": "Ed", "raw_text": "Ed is crowned King"}],
        }
    ]
    event_id = import_capture([record], apply=True)["event_ids"]["capture-first"]
    with Session() as session:
        rows = list(session.scalars(select(Series)))
        assert all(r.player1_score is None and r.result_unavailable for r in rows)
        games = session.scalars(select(DBSeriesGame))
        assert all(g.winner_side is None for g in games)
    history = client.get(f"/koth/nights/{event_id}/board").json()["brackets"][0][
        "history"
    ]
    # neither side of the break plays on, so its winner is unknown and left
    assert [r["inferred_winner_side"] for r in history] == [1, None, 2]
    assert [r["winner_left"] for r in history] == [False, True, False]
    assert [r["review_note"] for r in history] == [None, None, None]
    assert [r["winner_side"] for r in history] == [None, None, None]
    assert [r["throne"] for r in history] == ["moved", "none", "moved"]


def test_admin_delete_removes_an_archived_night(
    client: Client, auth_headers: dict[str, str]
) -> None:
    event_id = import_capture(capture(), apply=True)["event_ids"]["capture-first"]
    gone = client.delete(f"/events/{event_id}", headers=auth_headers)
    assert gone.status_code == 204
    assert counts() == (0, 0, 0, 0)
    with Session() as session:
        for model in (EventAward, EventEntrant, HistoricalParticipant):
            assert session.scalar(select(func.count()).select_from(model)) == 0


def archived(key: str, order: int, day: str | None, label: str) -> dict[str, Any]:
    """The capture's night under its own key, label and day."""
    record = deepcopy(capture()[0])
    record.update(event_id=key, source_order=order, date=day, date_text=label)
    return record


def crowned_night(client: Client, headers: dict[str, str]) -> tuple[int, int]:
    """A night run in the app whose strongest bracket crowned one player, closed."""
    night = open_night(client, headers)
    top = bracket_ids(night)[0]
    first = place(client, headers, night, "One#1", 1700, top)
    second = place(client, headers, night, "Two#2", 1700, top, race="OC")
    play(client, headers, night["id"], first, second)
    closed = client.post(f"/koth/nights/{night['id']}/close", headers=headers)
    assert closed.status_code == 200, closed.text
    return night["id"], first


def winners(client: Client, query: str = "") -> tuple[list[dict[str, Any]], Any]:
    response = client.get(f"/koth/winners{query}")
    assert response.status_code == 200, response.text
    return response.json(), response.headers


@pytest.mark.usefixtures("quiet_w3c")
def test_winners_list_the_king_of_every_bracket_of_a_closed_night(
    client: Client, auth_headers: dict[str, str]
) -> None:
    """An archived night names the source spelling, a native night the account."""
    record = archived("dated", 1, "2024-11-30", "November 30, 2024")
    old = import_capture([record], apply=True)["event_ids"]["dated"]
    native, first = crowned_night(client, auth_headers)
    with Session() as session:
        king = session.get(EventEntrant, first)
        assert king is not None and king.user_id is not None
        user_id = king.user_id
    brackets = client.get(f"/koth/nights/{native}/board").json()["brackets"]

    rows, headers = winners(client)

    assert headers["X-Total-Count"] == "2"
    assert headers["cache-control"] == (
        "public, s-maxage=3600, stale-while-revalidate=86400"
    )
    assert headers["access-control-allow-origin"] == "*"
    assert [row["event_id"] for row in rows] == [native, old]
    assert rows[0]["date"] == NIGHT[:10]
    assert rows[0]["date_label"] is None
    assert rows[0]["winners"] == [
        {
            "bracket": bracket["name"],
            "lower_bound": bracket["lower_bound"],
            "name": "One" if index == 0 else None,
            "user_id": user_id if index == 0 else None,
            "country": None,
            "race": "HU" if index == 0 else None,
        }
        for index, bracket in enumerate(brackets)
    ]
    assert rows[1] == {
        "event_id": old,
        "date": "2024-11-30",
        "date_label": "November 30, 2024",
        "winners": [
            {
                "bracket": "1500 to ~1700 MMR",
                "lower_bound": 1500,
                "name": "OTHER",
                "user_id": None,
                "country": None,
                "race": None,
            },
            {
                "bracket": "Gold and below",
                "lower_bound": None,
                "name": None,
                "user_id": None,
                "country": None,
                "race": None,
            },
        ],
    }


def test_a_linked_archived_name_shows_the_player(client: Client) -> None:
    """A reviewed link names the player; a rerun changes nothing, an unknown
    tag links nothing, and a name the links leave out is unlinked."""
    import_capture(
        [archived("dated", 1, "2024-11-30", "November 30, 2024")], apply=True
    )
    with Session.begin() as session:
        player = User(
            name="Other",
            discordTag=None,
            discordId=None,
            country="DE",
            race=Race.HU,
            battle_tags=active("Other#1234"),
        )
        session.add(player)
        session.flush()
        player_id = player.id

    def king() -> dict[str, Any]:
        return winners(client)[0][0]["winners"][0]

    dry = link_players({"other": "other#1234 "})
    assert dry["changed_rows"] > 0 and king()["user_id"] is None
    report = link_players({"other": "other#1234 ", "Nobody": "Nobody#1"}, apply=True)
    assert report["linked_rows"] == dry["linked_rows"]
    assert report["unknown_tags"] == ["Nobody#1"]
    assert (king()["name"], king()["user_id"], king()["country"]) == (
        "Other",
        player_id,
        "DE",
    )
    assert link_players({"OTHER": "Other#1234"}, apply=True)["changed_rows"] == 0
    link_players({}, apply=True)
    assert king()["user_id"] is None and king()["name"] == "OTHER"
    with pytest.raises(ValueError, match="battle tag"):
        link_players({"OTHER": 1234})


@pytest.mark.usefixtures("quiet_w3c")
def test_a_withdrawn_or_moved_crown_is_no_winner_as_on_the_board(
    client: Client, auth_headers: dict[str, str]
) -> None:
    """A crowned row that withdrew or stands in another bracket names no king."""
    native, first = crowned_night(client, auth_headers)
    with Session.begin() as session:
        king = session.get(EventEntrant, first)
        assert king is not None
        top, lower = session.scalars(
            select(EventDivision)
            .where(col(EventDivision.event_id) == native)
            .order_by(col(EventDivision.position))
            .limit(2)
        ).all()
        assert top.king_entrant_id == first
        king.withdrawn_at = utcnow()
        lower.king_entrant_id = first
    brackets = client.get(f"/koth/nights/{native}/board").json()["brackets"]

    rows, _ = winners(client)

    assert [bracket["king"] for bracket in brackets[:2]] == [None, None]
    assert [winner["name"] for winner in rows[0]["winners"][:2]] == [None, None]
    assert {winner["user_id"] for winner in rows[0]["winners"]} == {None}


@pytest.mark.usefixtures("quiet_w3c")
def test_an_open_or_unpublished_night_has_no_winners(
    client: Client, auth_headers: dict[str, str]
) -> None:
    hidden = import_capture(capture(), apply=True)["event_ids"]["capture-first"]
    with Session.begin() as session:
        event = session.get(Season, hidden)
        assert event is not None
        event.published = False
    open_night(client, auth_headers)

    rows, headers = winners(client)
    assert rows == []
    assert headers["X-Total-Count"] == "0"


@pytest.mark.usefixtures("quiet_w3c")
def test_winners_page_by_night_newest_start_first(
    client: Client, auth_headers: dict[str, str]
) -> None:
    """A native night dates by its start time, an archived one by its start date;
    an undated night stands last and a night with no bracket lists empty."""
    undated = archived("undated", 1, None, "Some night")
    ids = import_capture([undated], apply=True)["event_ids"]
    _, alone = winners(client)
    empty = archived("empty", 2, "2025-01-04", "January 4, 2025")
    empty["sections"] = [s for s in empty["sections"] if s["kind"] != "bracket"]
    older = archived("older", 3, "2023-05-06", "May 6, 2023")
    ids |= import_capture([empty, older], apply=True)["event_ids"]
    native, _ = crowned_night(client, auth_headers)
    order = [native, ids["empty"], ids["older"], ids["undated"]]

    rows, headers = winners(client)
    assert [row["event_id"] for row in rows] == order
    assert [row["date"] for row in rows] == [
        NIGHT[:10],
        "2025-01-04",
        "2023-05-06",
        None,
    ]
    assert rows[1]["winners"] == []
    assert [len(row["winners"]) for row in rows] == [3, 0, 2, 2]
    assert headers["X-Total-Count"] == "4"
    assert int(headers["X-DB-Statements"]) == int(alone["X-DB-Statements"]) <= 1

    page, headers = winners(client, "?limit=2&offset=1")
    assert [row["event_id"] for row in page] == order[1:3]
    assert headers["X-Total-Count"] == "4"
    last, _ = winners(client, "?limit=2&offset=3")
    assert [row["event_id"] for row in last] == order[3:]
    past, headers = winners(client, "?offset=4")
    assert past == []
    assert headers["X-Total-Count"] == "4"


def bracket(*rows: dict[str, Any], king: str) -> list[dict[str, Any]]:
    crown = {"player": king, "raw_text": f"{king} is crowned King"}
    return [
        {"kind": "bracket", "title": "Gold", "matches": list(rows), "crowns": [crown]}
    ]


def people(event_id: int) -> list[str]:
    with Session() as session:
        return list(
            session.scalars(
                select(col(HistoricalParticipant.source_name))
                .where(col(HistoricalParticipant.event_id) == event_id)
                .order_by(col(HistoricalParticipant.source_key))
            )
        )


def test_a_corrected_typo_is_one_participant_and_frees_the_order_of_play(
    client: Client,
) -> None:
    """The kept name joins a typo pair; the stored source stays as written."""
    plain = archived("plain", 1, "2024-11-30", "November 30, 2024")
    plain["sections"] = bracket(
        bo1("Regitheth", "Bo"), bo1("Regitheht", "Cy"), king="Cy"
    )
    joined = deepcopy(plain)
    joined["event_id"] = "joined"
    untouched = deepcopy([plain, joined])
    fixes = {"names": {"regitheth": "Regitheht"}}

    dry = import_capture([joined], corrections=fixes)
    assert (dry["corrected_names"], dry["corrected_dates"]) == (1, 0)
    import_capture([plain], apply=True)
    result = import_capture([plain, joined], apply=True, corrections=fixes)
    ids = result["event_ids"]
    assert result["inserted_events"] == 1 and result["corrected_names"] == 2

    assert people(ids["plain"]) == ["Regitheth", "Bo", "Regitheht", "Cy"]
    assert people(ids["joined"]) == ["Regitheht", "Bo", "Cy"]  # Bo, Cy as written

    def inferred(key: str) -> list[int | None]:
        board = client.get(f"/koth/nights/{ids[key]}/board").json()
        return [row["inferred_winner_side"] for row in board["brackets"][0]["history"]]

    assert inferred("plain") == [None, 2]
    assert inferred("joined") == [1, 2]
    with Session() as session:
        archive = session.get(KothHistoryEvent, ids["joined"])
        assert archive is not None
        assert archive.source_record == untouched[1]
        assert archive.source_digest == digest(untouched[1])
        stored = session.scalars(
            select(col(KothHistorySeries.source_record))
            .where(col(KothHistorySeries.event_id) == ids["joined"])
            .order_by(col(KothHistorySeries.series_id))
        ).all()
        assert stored == untouched[1]["sections"][0]["matches"]
    assert [plain, joined] == untouched
    again = import_capture([plain, joined], apply=True, corrections=fixes)
    assert again["inserted_events"] == 0 and again["event_ids"] == ids


def test_two_casings_of_one_name_are_one_participant(client: Client) -> None:
    record = archived("cased", 1, "2024-11-30", "November 30, 2024")
    record["sections"] = bracket(bo1("Elu", "Bo"), bo1("elu ", "Cy"), king="CY")
    event_id = import_capture([record], apply=True)["event_ids"]["cased"]
    assert people(event_id) == ["Elu", "Bo", "CY"]


def test_a_name_kept_as_itself_stores_one_casing_in_every_bracket(
    client: Client,
) -> None:
    fixes = {"names": {"elu": "Elu", "eluu": "Elu"}}
    first = archived("first", 1, "2024-11-30", "November 30, 2024")
    first["sections"] = bracket(bo1("ELU", "Bo"), bo1("eluu", "Cy"), king="Cy")
    second = archived("second", 2, "2024-11-23", "November 23, 2024")
    second["sections"] = bracket(bo1("Bo", "elu"), king="elu")
    ids = import_capture([first, second], apply=True, corrections=fixes)["event_ids"]
    assert people(ids["first"]) == ["Elu", "Bo", "Cy"]
    assert people(ids["second"]) == ["Bo", "Elu"]


def test_a_king_keeps_the_spelling_of_the_crown_line(client: Client) -> None:
    """A kept name first, then the crown line, then the first spelling in the series."""
    crowned = archived("crowned", 1, "2024-11-30", "November 30, 2024")
    crowned["sections"] = bracket(
        bo1("glaive", "bo"), bo1("BO", "glaive"), king="Glaive"
    )
    corrected = archived("corrected", 2, "2024-11-23", "November 23, 2024")
    corrected["sections"] = bracket(
        bo1("glaiev", "bo"), bo1("BO", "glaive"), king="Glaive"
    )
    fixes = {"names": {"glaiev": "glaive"}}
    ids = import_capture([crowned, corrected], apply=True, corrections=fixes)[
        "event_ids"
    ]

    assert people(ids["crowned"]) == ["Glaive", "bo"]
    assert people(ids["corrected"]) == ["glaive", "bo"]
    for key, king in (("crowned", "Glaive"), ("corrected", "glaive")):
        board = client.get(f"/koth/nights/{ids[key]}/board").json()
        assert board["brackets"][0]["historical_king"]["name"] == king
        assert {row["side2"]["name"] for row in board["brackets"][0]["history"]} == {
            "bo",
            king,
        }
    rows, _ = winners(client)
    assert [row["event_id"] for row in rows] == [ids["crowned"], ids["corrected"]]
    assert [row["winners"][0]["name"] for row in rows] == ["Glaive", "glaive"]


def test_a_reviewed_date_dates_an_undated_night_before_page_order(
    client: Client,
) -> None:
    records = [
        archived("newer", 1, "2022-03-06", "March 6, 2022"),
        archived("between", 2, None, "February 26"),
        archived("impossible", 3, None, "November 31, 2021"),
        archived("older", 4, "2021-10-23", "October 23, 2021"),
    ]
    with pytest.raises(ValueError, match="has its own date"):
        import_capture(
            records, apply=True, corrections={"dates": {"newer": "2022-03-06"}}
        )
    assert counts() == (0, 0, 0, 0)
    fixes = {
        "dates": {
            "between": "2022-02-25",
            "impossible": "2021-11-30",
            "elsewhere": "2020-01-01",
        }
    }
    days = record_days(
        records, {key: date.fromisoformat(day) for key, day in fixes["dates"].items()}
    )
    assert days["between"] == date(2022, 2, 25)
    assert days["impossible"] == date(2021, 11, 30)
    assert record_days(records)["between"] == date(2022, 2, 26)

    result = import_capture(records, apply=True, corrections=fixes)
    assert result["corrected_dates"] == 2
    with Session() as session:
        for key, name, day in (
            ("between", "KOTH February 25, 2022", date(2022, 2, 25)),
            ("impossible", "KOTH November 30, 2021", date(2021, 11, 30)),
        ):
            event = session.get(Season, result["event_ids"][key])
            assert event is not None and event.name == name
            assert event.start_date == event.end_date == day
            round_ = session.scalars(
                select(DBEventRound).where(
                    col(DBEventRound.season_id) == result["event_ids"][key]
                )
            ).one()
            assert round_.start_date == round_.end_date == day
            archive = session.get(KothHistoryEvent, result["event_ids"][key])
            assert archive is not None
            assert archive.date_label == {"between": "February 26"}.get(
                key, "November 31, 2021"
            )


@pytest.mark.parametrize(
    ("names", "error"),
    [
        ({"elusieri": "elusirei", "elusirei": "Elusirel"}, "itself corrected"),
        ({"a": "B", "b": "C"}, "itself corrected"),
        ({"elu": " "}, "empty name"),
        ({"Elu": "Elusirel"}, "folded spelling"),
    ],
)
def test_a_bad_corrections_file_fails_before_any_write(
    client: Client, names: dict[str, str], error: str
) -> None:
    with pytest.raises(ValueError, match=error):
        import_capture(capture(), apply=True, corrections={"names": names})
    assert counts() == (0, 0, 0, 0)


def test_a_corrections_file_that_is_not_an_object_fails_before_any_write(
    client: Client,
) -> None:
    with pytest.raises(ValueError, match="not a JSON object"):
        import_capture(capture(), apply=True, corrections=json.loads('[{"names": {}}]'))
    assert counts() == (0, 0, 0, 0)


def history(client: Client, *rows: dict[str, Any], king: str) -> list[dict[str, Any]]:
    """The board rows of a one-bracket archived night."""
    record = archived("marks", 1, "2024-11-30", "November 30, 2024")
    record["sections"] = bracket(*rows, king=king)
    event_id = import_capture([record], apply=True)["event_ids"]["marks"]
    response = client.get(f"/koth/nights/{event_id}/board")
    assert response.status_code == 200, response.text
    assert int(response.headers["X-DB-Statements"]) == 6
    return response.json()["brackets"][0]["history"]


def thrones(client: Client, *rows: dict[str, Any], king: str) -> list[str]:
    """What each row of a one-bracket archived night did to the crown."""
    return [row["throne"] for row in history(client, *rows, king=king)]


def test_a_winner_who_left_empties_the_throne(client: Client) -> None:
    rows = [
        bo1("Ann", "Bo"),
        bo1("Ann", "Cy", winner="Cy"),
        bo1("Ann", "Di"),
        bo1("Ed", "Fay"),
        bo1("Ed", "Gus"),
    ]
    marks = [
        (
            row["winner_side"],
            row["inferred_winner_side"],
            row["winner_left"],
            row["throne"],
            row["review_note"],
        )
        for row in history(client, *rows, king="Gus")
    ]
    assert marks == [
        (None, 1, False, "moved", None),
        (2, None, True, "moved", None),  # the written winner stands, Ann plays on
        (None, None, True, "none", None),  # a break: nobody holds the crown going in
        (None, 1, False, "moved", None),
        (None, 2, False, "moved", None),
    ]


def test_a_break_on_the_first_pairing_has_no_winner(client: Client) -> None:
    rows = [bo1("Ann", "Bo"), bo1("Cy", "Di"), bo1("Cy", "Ed")]
    marks = [
        (row["inferred_winner_side"], row["winner_left"], row["throne"])
        for row in history(client, *rows, king="Ed")
    ]
    assert marks == [(None, True, "none"), (1, False, "moved"), (2, False, "moved")]


@pytest.mark.parametrize("written", [False, True])
def test_an_archived_chain_marks_the_crown_as_a_played_row_does(
    client: Client, written: bool
) -> None:
    """A written winner and an inferred one mark the crown alike."""
    rows = [bo1("Ann", "Bo"), bo1("Ann", "Cy"), bo1("Ann", "Di"), bo1("Di", "Ed")]
    if written:
        rows[1]["winner"], rows[2]["winner"] = "Ann", "Di"
    assert thrones(client, *rows, king="Di") == ["moved", "held", "moved", "held"]


def test_after_an_unknown_result_only_the_last_holder_holds_the_crown(
    client: Client,
) -> None:
    rows = [
        bo1("Ann", "Bo", winner="Ann"),
        bo1("Ann", "Cy", "(Cy had to leave)"),
        bo1("Ann", "Di", winner="Ann"),
        bo1("Ann", "Ed"),
        bo1("Ann", "Ed", winner="Ed"),
        bo1("Fay", "Gus"),
        bo1("Fay", "Gus", winner="Gus"),
    ]
    assert thrones(client, *rows, king="Gus") == [
        "moved",
        "none",
        "held",  # the last holder wins
        "none",
        "moved",  # the last holder plays and loses
        "none",
        "moved",  # the last holder does not play
    ]
