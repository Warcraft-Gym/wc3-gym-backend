"""The league beside the event name: the helper, and every payload that carries it.

The seeded season stands in no league, so this file puts it in one named GNL
and reads the payloads back. A payload of an event with no league reads null,
which the GNL snapshot pins.
"""

from typing import Any

import pytest
from fastapi.testclient import TestClient as Client

from app.core.db import Session
from app.core.event_label import label
from app.models.league import League
from app.models.season import Season
from app.models.series import Series
from app.services import series_cards
from app.services.events import EventService
from app.services.series import SeriesService
from tests.test_player_session import member_session


@pytest.fixture
def in_gnl(seeded: dict[str, Any]) -> dict[str, Any]:
    """The seeded season, moved into a league whose short name is GNL."""
    with Session.begin() as session:
        league = League(name="Grand National League", short_name="GNL")
        session.add(league)
        session.flush()
        season = session.get(Season, seeded["season_id"])
        assert season is not None
        season.league_id = league.id
    return seeded


def test_the_label_puts_the_league_short_name_before_the_event() -> None:
    assert label("Season 18", "GNL") == "GNL · Season 18"


def test_the_label_leaves_a_name_that_already_opens_with_the_short_name() -> None:
    assert label("GNL Season 18", "GNL") == "GNL Season 18"


def test_the_label_is_the_name_alone_when_the_event_has_no_league() -> None:
    assert label("KOTH night", None) == "KOTH night"
    assert label("KOTH night", "") == "KOTH night"


def test_the_label_of_an_event_with_no_name_still_names_the_league() -> None:
    assert label(None, "GNL") == "GNL · ?"
    assert label(None, None) == "?"


def test_the_season_payloads_name_the_league(
    client: Client, in_gnl: dict[str, Any]
) -> None:
    """The full read, the list read and the nested read all carry it."""
    season_id = in_gnl["season_id"]
    one = client.get(f"/seasons/{season_id}")
    assert one.status_code == 200, one.text
    assert one.json()["league_short_name"] == "GNL"
    listed = client.get("/seasons").json()
    assert [row["league_short_name"] for row in listed] == ["GNL"]
    # The reduced form a match nests under itself
    match_id = in_gnl["match_id"]
    nested = client.get(f"/matches/{match_id}").json()
    assert nested["season"]["league_short_name"] == "GNL"


def test_the_event_payload_names_the_league(
    client: Client, in_gnl: dict[str, Any], auth_headers: dict[str, str]
) -> None:
    one = client.get(f"/events/{in_gnl['season_id']}", headers=auth_headers)
    assert one.status_code == 200, one.text
    assert one.json()["league_short_name"] == "GNL"


def test_the_member_home_row_names_the_league(in_gnl: dict[str, Any]) -> None:
    rows = EventService().events_for_member(None)
    assert [row.league_short_name for row in rows] == ["GNL"]


def test_the_me_seasons_name_the_league(
    client: Client, in_gnl: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    answer = client.get("/me", headers=member_session(monkeypatch)).json()
    assert [row["league_short_name"] for row in answer["seasons"]] == ["GNL"]


def test_the_history_events_and_meetings_name_the_league(
    client: Client, in_gnl: dict[str, Any]
) -> None:
    player = in_gnl["player_ids"][0]
    history = client.get(f"/users/{player}/history").json()
    assert [row["league_short_name"] for row in history["events"]] == ["GNL"]
    meetings = [
        meeting for opponent in history["opponents"] for meeting in opponent["meetings"]
    ]
    assert meetings
    assert {meeting["league_short_name"] for meeting in meetings} == {"GNL"}


def test_the_trophy_names_the_league(client: Client, in_gnl: dict[str, Any]) -> None:
    """Scoring the one open series finishes the season and crowns Alpha."""
    with Session.begin() as session:
        series = session.get(Series, in_gnl["series_open_id"])
        assert series is not None
        series.player1_score, series.player2_score = 2, 0
    trophies = client.get(f"/users/{in_gnl['player_ids'][0]}").json()["trophies"]
    assert [row["league_short_name"] for row in trophies] == ["GNL"]


def test_the_card_header_prints_the_league_before_the_event(
    in_gnl: dict[str, Any],
) -> None:
    series = SeriesService().get(in_gnl["series_open_id"])
    assert series_cards.header(series)[0] == "## GNL · Season 1"


def test_the_card_header_of_an_event_with_no_league_prints_the_name_alone(
    seeded: dict[str, Any],
) -> None:
    series = SeriesService().get(seeded["series_open_id"])
    assert series_cards.header(series)[0] == "## Season 1"
