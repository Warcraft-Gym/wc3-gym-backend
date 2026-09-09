"""A series that was never played is recorded 0-0.

An admin may store it, so a season with an abandoned fixture can still read
complete. A player may not: voiding his own series would drop a game he was
losing out of the standings, so the report path still needs a finished result.
"""

from collections.abc import Callable
from typing import Any

from httpx2 import Client

from app.core.db import Session
from app.models.season import Season


def phase_of(season_id: int) -> str:
    with Session() as session:
        season = session.get(Season, season_id)
        assert season is not None
        return season.progress(session).phase


def test_an_admin_records_a_series_that_was_never_played(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    """The seeded season is past its end date with one series unscored, the
    state GNL S17 sits in."""
    assert phase_of(seeded["season_id"]) == "overdue"

    resp = client.put(
        f"/series/{seeded['series_open_id']}",
        json={"player1_score": 0, "player2_score": 0},
        headers=auth_headers,
    )

    assert resp.status_code == 200, resp.text
    assert (resp.json()["player1_score"], resp.json()["player2_score"]) == (0, 0)
    assert phase_of(seeded["season_id"]) == "complete"


def test_a_never_played_series_pays_neither_team(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    """Alpha won the one played series, and the 0-0 leaves the standings alone."""
    before = client.get(f"/teams/season/{seeded['season_id']}").json()
    scores = {team["name"]: team["seasons_info"][0]["final_score"] for team in before}

    resp = client.put(
        f"/series/{seeded['series_open_id']}",
        json={"player1_score": 0, "player2_score": 0},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text

    after = client.get(f"/teams/season/{seeded['season_id']}").json()
    assert {t["name"]: t["seasons_info"][0]["final_score"] for t in after} == scores


def test_an_undecided_score_is_still_refused(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    """0-0 is the only pair that is not a finished series and still stores."""
    resp = client.put(
        f"/series/{seeded['series_open_id']}",
        json={"player1_score": 1, "player2_score": 1},
        headers=auth_headers,
    )

    assert resp.status_code == 400, resp.text
    assert resp.json() == {
        "error": "A series of this season ends at 2 map wins, or 0-0 when it was never played"
    }


def test_a_player_cannot_void_his_own_series(
    client: Client, seeded: dict[str, Any], member: Callable[..., dict[str, str]]
) -> None:
    """Only an admin records a series as never played."""
    resp = client.put(
        f"/player-series/{seeded['series_open_id']}",
        headers=member("2"),
        json={"action": "score_updated", "player1_score": 0, "player2_score": 0},
    )

    assert resp.status_code == 400, resp.text
    assert resp.json() == {"error": "A series of this season ends at 2 map wins."}
