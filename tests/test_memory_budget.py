"""Pin the peak memory one fantasy bets list answer costs.

FantasyBet.list_eager_options and the reduced builders decide the cost,
and the cost per bet is flat: it does not grow with the seasons a
player signed up for, the stats the player carries or the maps a season
holds. A collection put back into the list serialization multiplies the
peak by the season count and fails the budget here.
"""

import tracemalloc
from typing import Any

import pytest
from fastapi import FastAPI

from app.core.db import Session
from app.models.enums import Race
from app.models.fantasy_bet import FantasyBet
from app.models.relationships import DBUserSeasonSignup
from app.models.season import Season
from app.models.w3c_stats import W3CStats
from app.services.fantasy_bets import FantasyBetService

BETS = 300
SEASONS = 8
BUDGET_BYTES = 8 * 1024 * 1024


@pytest.fixture
def crowded(app: FastAPI, seeded: dict[str, Any]) -> dict[str, Any]:
    """The seeded league with many bets and many seasons per player."""
    with Session() as session:
        seasons = [
            Season(name=f"Season {n}", number_weeks=4, series_per_week=2)
            for n in range(2, SEASONS + 2)
        ]
        session.add_all(seasons)
        session.flush()
        for user_id in seeded["player_ids"]:
            for season in seasons:
                session.add(DBUserSeasonSignup(user_id=user_id, season_id=season.id))
            session.add(
                W3CStats(user_id=user_id, wc3_season=20, race=Race.HU, mmr=1500)
            )
        for _ in range(BETS):
            session.add(
                FantasyBet(
                    season_id=seeded["season_id"],
                    series_id=seeded["series_played_id"],
                    user_id=seeded["player_ids"][0],
                    winner_id=seeded["player_ids"][0],
                    bet_points=10,
                )
            )
        session.commit()
    return seeded


def test_bets_list_peak_stays_in_budget(crowded: dict[str, Any]) -> None:
    """The list answer keeps its peak under the pinned budget."""
    service = FantasyBetService()
    tracemalloc.start()
    bets, total = service.getAll()
    _, peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert len(bets) == BETS + 1
    assert total is None
    assert peak < BUDGET_BYTES, f"peak {peak / 1024 / 1024:.1f} MB"
