"""The scoring rule has two faces, and they must give the same value.

app.core.scoring holds the rule once: points() for Python and points_case() for SQL.
The parity test runs every map score pair through both faces, and the oracle test
holds the Python face against ScoreService, the rule the application uses today.
"""

from typing import Any

import pytest
from fastapi import FastAPI
from httpx2 import Client
from sqlalchemy import Integer, literal, select

from app.core.scoring import MAX_POINTS, max_points, points, points_case
from tests.test_score_service import make_service

SCORES = [None, 0, 1, 2]
SYSTEMS = list(MAX_POINTS)
COMBOS = [(own, opp, system) for own in SCORES for opp in SCORES for system in SYSTEMS]


def raises_on(own: int | None, opp: int | None) -> bool:
    """One score without the other is a half reported result, and it raises."""
    return (own is None) != (opp is None)


def sql_points(own: int | None, opp: int | None, system: str) -> int | None:
    from app.core.db import Session

    with Session() as session:
        return session.scalar(
            select(points_case(literal(own, Integer), literal(opp, Integer), system))
        )


@pytest.mark.parametrize("own,opp,system", COMBOS)
def test_python_and_sql_give_the_same_points(
    app: FastAPI, own: int | None, opp: int | None, system: str
) -> None:
    if raises_on(own, opp):
        with pytest.raises(ValueError, match="Score is not valid"):
            points(own, opp, system)
        # SQL cannot raise, so this pair has no database value to compare
        return

    assert points(own, opp, system) == sql_points(own, opp, system)


@pytest.mark.parametrize("own,opp,system", COMBOS)
def test_points_gives_what_the_score_service_gives(
    own: int | None, opp: int | None, system: str
) -> None:
    service = make_service(system)
    if raises_on(own, opp):
        with pytest.raises(Exception, match="Score is not valid"):
            service.getScoreByMapScore(own, opp)
        with pytest.raises(ValueError, match="Score is not valid"):
            points(own, opp, system)
        return

    assert points(own, opp, system) == service.getScoreByMapScore(own, opp)


@pytest.mark.parametrize("system", SYSTEMS)
def test_max_points_gives_what_the_score_service_gives(system: str) -> None:
    assert max_points(system) == make_service(system).getMaxPointsPerSeries()


def test_an_unknown_score_system_reads_as_standard() -> None:
    assert max_points("no such system") == 3
    assert points(2, 0, "no such system") == 3


def test_a_new_season_carries_a_score_system(
    client: Client, auth_headers: dict[str, str]
) -> None:
    created = client.post(
        "/seasons",
        json={"name": "Season 9", "number_weeks": 4, "series_per_week": 2},
        headers=auth_headers,
    )
    assert created.status_code == 201
    assert created.json()["score_system"] == "standard"

    season_id = created.json()["id"]
    updated = client.put(
        f"/seasons/{season_id}",
        json={"score_system": "helpstone"},
        headers=auth_headers,
    )
    assert updated.status_code == 200
    assert updated.json()["score_system"] == "helpstone"

    fetched: dict[str, Any] = client.get(f"/seasons/{season_id}").json()
    assert fetched["score_system"] == "helpstone"
    assert fetched["name"] == "Season 9"
