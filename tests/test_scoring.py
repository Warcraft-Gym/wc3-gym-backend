"""The scoring rule has two faces, and they must give the same value.

app.core.scoring holds the rule once: points() for Python and points_case() for SQL.
The parity test runs every map score pair through both faces, and the oracle test
holds the Python face against the GNL scale, written out pair by pair.
"""

from typing import Any

import pytest
from fastapi import FastAPI
from httpx2 import Client
from sqlalchemy import Integer, literal, select

from app.core.scoring import SYSTEMS, max_points, points, points_case, wins_needed

SCORES = [None, 0, 1, 2]
COMBOS = [(own, opp, system) for own in SCORES for opp in SCORES for system in SYSTEMS]
WINS = [1, 2, 3]  # Bo1, Bo3, Bo5
WIDE = [
    (own, opp, system, wins)
    for wins in WINS
    for own in [None, *range(wins + 1)]
    for opp in [None, *range(wins + 1)]
    for system in SYSTEMS
]

# The GNL scale, as (own score, opponent score): what each system pays. A loser
# keeps its map score, and a 2-x win pays from the top of its own scale.
ORACLE: dict[tuple[int | None, int | None], dict[str, int | None]] = {
    (None, None): {"standard": None, "helpstone": None},
    (0, 0): {"standard": 0, "helpstone": 0},
    (0, 1): {"standard": 0, "helpstone": 0},
    (0, 2): {"standard": 0, "helpstone": 0},
    (1, 0): {"standard": 1, "helpstone": 1},
    (1, 1): {"standard": 1, "helpstone": 1},
    (1, 2): {"standard": 1, "helpstone": 1},
    (2, 0): {"standard": 3, "helpstone": 4},
    (2, 1): {"standard": 2, "helpstone": 3},
    # No series ends 2-2, so the rule pays nothing for it
    (2, 2): {"standard": None, "helpstone": None},
}


def raises_on(own: int | None, opp: int | None) -> bool:
    """One score without the other is a half reported result, and it raises."""
    return (own is None) != (opp is None)


def sql_points(
    own: int | None, opp: int | None, system: str, wins: int = 2
) -> int | None:
    from app.core.db import Session

    with Session() as session:
        return session.scalar(
            select(
                points_case(literal(own, Integer), literal(opp, Integer), system, wins)
            )
        )


@pytest.mark.parametrize("own,opp,system,wins", WIDE)
def test_python_and_sql_give_the_same_points(
    app: FastAPI, own: int | None, opp: int | None, system: str, wins: int
) -> None:
    if raises_on(own, opp):
        with pytest.raises(ValueError, match="Score is not valid"):
            points(own, opp, system, wins)
        # SQL cannot raise, so this pair has no database value to compare
        return

    assert points(own, opp, system, wins) == sql_points(own, opp, system, wins)


@pytest.mark.parametrize("own,opp,system", COMBOS)
def test_points_gives_the_gnl_scale(
    own: int | None, opp: int | None, system: str
) -> None:
    if raises_on(own, opp):
        with pytest.raises(ValueError, match="Score is not valid"):
            points(own, opp, system)
        return

    assert points(own, opp, system) == ORACLE[(own, opp)][system]


# The same scale for a Bo1 and a Bo5, as (own, opp): the winner takes the top of
# the scale minus the loser's maps, and the loser keeps its maps
BEST_OF_ORACLE: dict[tuple[int, int, int], dict[str, int]] = {
    (1, 1, 0): {"standard": 1, "helpstone": 2},
    (3, 3, 0): {"standard": 5, "helpstone": 6},
    (3, 3, 1): {"standard": 4, "helpstone": 5},
    (3, 3, 2): {"standard": 3, "helpstone": 4},
    (3, 2, 3): {"standard": 2, "helpstone": 2},
}


@pytest.mark.parametrize("wins,own,opp", list(BEST_OF_ORACLE))
@pytest.mark.parametrize("system", SYSTEMS)
def test_points_extends_the_scale_to_any_best_of(
    wins: int, own: int, opp: int, system: str
) -> None:
    assert points(own, opp, system, wins) == BEST_OF_ORACLE[(wins, own, opp)][system]


def test_a_score_above_the_maps_a_win_takes_is_not_valid() -> None:
    with pytest.raises(ValueError, match="Score is not valid"):
        points(3, 0, "standard")
    assert points(3, 3, "standard", 3) is None


@pytest.mark.parametrize(
    "map_rules,wins",
    [
        (None, 2),
        ("", 2),
        ("veto", 1),
        ("veto,veto,veto", 2),
        ("veto,veto,veto,veto,veto", 3),
    ],
)
def test_wins_needed_reads_the_best_of_off_the_map_rules(
    map_rules: str | None, wins: int
) -> None:
    assert wins_needed(map_rules) == wins


@pytest.mark.parametrize("system,top", [("standard", 3), ("helpstone", 4)])
def test_max_points_tops_the_scale_of_its_system(system: str, top: int) -> None:
    assert max_points(system) == top
    assert max_points(system, 3) == top + 2


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
