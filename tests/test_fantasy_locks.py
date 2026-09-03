"""The public fantasy writes close with the schedule.

A bet closes once its series has started and reopens if the series moves
later. A fantasy team is drafted while the season is open: before any series
is scored or past its time. The admin routes stay open, so a mistake is fixed there.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx2 import Client

from app.core.db import Session
from app.models.series import Series
from tests.test_public_token import member_session

CLOSED = {
    "error": "series_started",
    "message": "Bets close once the series has started",
}
ENDED = {"error": "season_ended", "message": "The season has ended"}
COMMENCED = {"error": "season_commenced", "message": "The season has commenced"}


def schedule(series_id: int, when: datetime | None) -> None:
    with Session.begin() as session:
        series = session.get(Series, series_id)
        assert series is not None
        series.date_time = when


def score(series_id: int, p1: int | None, p2: int | None) -> None:
    with Session.begin() as session:
        series = session.get(Series, series_id)
        assert series is not None
        series.player1_score, series.player2_score = p1, p2


def test_a_bet_closes_once_its_series_has_started(
    client: Client,
    seeded: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    auth_headers: dict[str, str],
) -> None:
    """P1's seeded bet sits on the played series; the open series has no time yet."""
    headers = member_session(monkeypatch, "1", "p1")
    bet_id = client.get("/fantasy/bets").json()[0]["id"]

    resp = client.put(f"/fantasy-bet/{bet_id}", json={"bet_points": 5}, headers=headers)
    assert (resp.status_code, resp.json()) == (403, CLOSED), resp.text
    resp = client.delete(f"/fantasy-bet/{bet_id}", headers=headers)
    assert (resp.status_code, resp.json()) == (403, CLOSED), resp.text

    bet = {
        "series_id": seeded["series_played_id"],
        "season_id": seeded["season_id"],
        "winner_id": seeded["player_ids"][0],
        "bet_points": 10,
    }
    resp = client.post("/fantasy-bet", json=bet, headers=headers)
    assert (resp.status_code, resp.json()) == (403, CLOSED), resp.text

    bet["series_id"] = seeded["series_open_id"]
    bet["winner_id"] = seeded["player_ids"][1]
    resp = client.post("/fantasy-bet", json=bet, headers=headers)
    assert resp.status_code == 201, resp.text

    # The admin route is the override
    resp = client.put(
        f"/fantasy/bets/{bet_id}", json={"bet_points": 5}, headers=auth_headers
    )
    assert resp.status_code == 200, resp.text


def test_a_series_moved_later_reopens_its_bets(
    client: Client, seeded: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    headers = member_session(monkeypatch, "1", "p1")
    bet_id = client.get("/fantasy/bets").json()[0]["id"]
    schedule(seeded["series_played_id"], datetime.now(UTC) + timedelta(days=1))

    resp = client.put(f"/fantasy-bet/{bet_id}", json={"bet_points": 5}, headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["bet_points"] == 5


def test_a_team_is_drafted_only_while_the_season_is_open(
    client: Client, seeded: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The seeded season has one played series, so it has commenced."""
    headers = member_session(monkeypatch, "1", "p1")
    team = {
        "name": "Late",
        "season_id": seeded["season_id"],
        "drafted_team_id": seeded["team_a_id"],
        "drafted_race": "HU",
        "player_ids": [],
    }
    resp = client.post("/fantasy-team", json=team, headers=headers)
    assert (resp.status_code, resp.json()) == (403, COMMENCED), resp.text

    # No series scored or past its time: the season is open again
    score(seeded["series_played_id"], None, None)
    schedule(seeded["series_played_id"], datetime.now(UTC) + timedelta(days=1))
    resp = client.post("/fantasy-team", json=team, headers=headers)
    assert resp.status_code == 201, resp.text
    assert resp.json()["name"] == "Late"

    # A scored series is done whether or not it carries a time
    score(seeded["series_played_id"], 2, 1)
    score(seeded["series_open_id"], 2, 0)
    resp = client.post("/fantasy-team", json=team, headers=headers)
    assert (resp.status_code, resp.json()) == (403, ENDED), resp.text
