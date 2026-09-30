"""A player's trophies: the finished seasons his team won.

The seeded league is not closed, so its season is still running and pays
nobody, whatever results it holds. Closing the season crowns Alpha.
"""

from typing import Any

from fastapi.testclient import TestClient as Client
from sqlmodel import col, select

from app.core.db import Session
from app.models.season import Season
from app.models.series import Series
from app.models.types import utcnow


def _score_the_open_series(seeded: dict[str, Any]) -> None:
    """Score the one open series, so every series of the season has a result."""
    with Session.begin() as session:
        series = session.scalars(
            select(Series).where(col(Series.id) == seeded["series_open_id"])
        ).one()
        series.player1_score = 2
        series.player2_score = 0


def _finish_the_season(seeded: dict[str, Any]) -> None:
    """Close the season, which is the one thing that finishes it."""
    with Session.begin() as session:
        season = session.get(Season, seeded["season_id"])
        assert season is not None
        season.closed_at = utcnow()


def _trophies(client: Client, user_id: int) -> list[dict[str, Any]]:
    resp = client.get(f"/users/{user_id}")
    assert resp.status_code == 200, resp.text
    return resp.json()["trophies"]


def test_a_season_still_running_pays_no_trophy(
    client: Client, seeded: dict[str, Any]
) -> None:
    """Alpha leads the seeded season, but nobody closed it yet."""
    assert _trophies(client, seeded["player_ids"][0]) == []

    # Every series it holds being scored still leaves the next round to draft
    _score_the_open_series(seeded)
    assert _trophies(client, seeded["player_ids"][0]) == []


def test_the_champion_roster_of_a_finished_season_earns_a_trophy(
    client: Client, seeded: dict[str, Any]
) -> None:
    _finish_the_season(seeded)

    assert _trophies(client, seeded["player_ids"][0]) == [
        {
            "title": "Season 1 Champion",
            "season_id": seeded["season_id"],
            "season_name": "Season 1",
            "league_short_name": "SL",
            "team_id": seeded["team_a_id"],
            "team_name": "Alpha",
            "team_icon_url": None,
        }
    ]


def test_the_beaten_team_earns_no_trophy(
    client: Client, seeded: dict[str, Any]
) -> None:
    _finish_the_season(seeded)

    assert _trophies(client, seeded["player_ids"][2]) == []
