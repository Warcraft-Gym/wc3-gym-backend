"""Pin how many statements one series answer costs.

Series._eager_options and DraftSeries._eager_options decide the count, and
the count is a constant: it does not grow with the number of w3c_stats,
team_seasons or season signups a player carries. A lazy load added to the
serialization raises the count and fails a test here.

The last test layers raiseload on the paths the options cover, so an
unintended lazy load on those paths raises instead of passing silently.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest
from fastapi import FastAPI
from sqlalchemy import event, select
from sqlalchemy.orm import joinedload

from app.core.db import Session
from app.core.query import QueryUtil
from app.models.draft_series import DraftSeries
from app.models.enums import Race
from app.models.relationships import DBUserSeasonSignup
from app.models.series import Series, SeriesPublic
from app.models.w3c_stats import W3CStats
from app.services.draft_series import DraftSeriesService
from app.services.series import SeriesService

STATS_PER_PLAYER = 8


@contextmanager
def count_statements() -> Iterator[list[int]]:
    """Report how many statements the engine sent inside the block."""
    with Session() as session:
        engine = session.get_bind()
    tally = [0]

    def on_execute(*args: object) -> None:
        tally[0] += 1

    event.listen(engine, "before_cursor_execute", on_execute)
    try:
        yield tally
    finally:
        event.remove(engine, "before_cursor_execute", on_execute)


@pytest.fixture
def league(app: FastAPI, seeded: dict[str, Any]) -> dict[str, Any]:
    """The seeded league, with the collections a series answer reads filled.

    Every player carries several w3c_stats rows and a season signup, and the
    match carries one draft series, so a per-row lazy load is visible.
    """
    with Session() as session:
        for user_id in seeded["player_ids"]:
            for season in range(STATS_PER_PLAYER):
                session.add(
                    W3CStats(
                        user_id=user_id,
                        wc3_season=season,
                        race=Race.HU,
                        wins=season,
                        losses=season,
                        games=2 * season,
                        mmr=1500 + season,
                    )
                )
            session.add(
                DBUserSeasonSignup(user_id=user_id, season_id=seeded["season_id"])
            )
        session.add(
            DraftSeries(
                match_id=seeded["match_id"],
                player1_id=seeded["player_ids"][0],
                player2_id=seeded["player_ids"][2],
                host_player_id=seeded["player_ids"][0],
            )
        )
        session.commit()
    return seeded


def test_get_series_costs_seven_statements(league: dict[str, Any]) -> None:
    service = SeriesService(score_app_service=None, user_app_service=None)
    with count_statements() as tally:
        series = service.get(league["series_played_id"])
    assert series.player1.w3c_stats
    assert tally[0] == 7


def test_search_for_season_costs_seven_statements(league: dict[str, Any]) -> None:
    service = SeriesService(score_app_service=None, user_app_service=None)
    query = QueryUtil.parseQuery("player1_id > 0")
    with count_statements() as tally:
        series_list = service.searchForSeason(league["season_id"], query)
    assert len(series_list) == 2
    assert tally[0] == 7


def test_career_stats_rows_cost_one_statement(league: dict[str, Any]) -> None:
    """The career recalculation input is one row per series, not the answer."""
    service = SeriesService(score_app_service=None, user_app_service=None)
    with count_statements() as tally:
        rows = service.career_stats_rows()
    assert len(rows) == 2
    assert rows[0].season_id == league["season_id"]
    assert tally[0] == 1


def test_user_season_stats_cost_two_statements(league: dict[str, Any]) -> None:
    """One statement for the counts and one for the matchup history."""
    service = SeriesService(score_app_service=None, user_app_service=None)
    with count_statements() as tally:
        stats = service.calculateUserSeasonStats(
            league["player_ids"][0], league["season_id"], league["team_a_id"]
        )
    assert stats.games == 1
    assert tally[0] == 2


def test_draft_series_by_match_costs_seven_statements(league: dict[str, Any]) -> None:
    service = DraftSeriesService()
    with count_statements() as tally:
        draft_list = service.getByMatchId(league["match_id"])
    assert len(draft_list) == 1
    assert tally[0] == 7


def test_statement_count_holds_when_the_collections_grow(
    league: dict[str, Any],
) -> None:
    """Four times the w3c_stats rows, the same number of statements."""
    with Session() as session:
        for user_id in league["player_ids"]:
            for season in range(STATS_PER_PLAYER, 4 * STATS_PER_PLAYER):
                session.add(W3CStats(user_id=user_id, wc3_season=season, race=Race.HU))
        session.commit()

    service = SeriesService(score_app_service=None, user_app_service=None)
    with count_statements() as tally:
        series = service.get(league["series_played_id"])
    assert len(series.player1.w3c_stats) == 4 * STATS_PER_PLAYER
    assert tally[0] == 7


def test_options_cover_the_player_graph(league: dict[str, Any]) -> None:
    """raiseload on both players, so a lazy load there raises.

    The wildcard covers the relationships of a player the options do not
    name, so dropping any of the three player options fails this test.
    """
    options = (
        *Series._eager_options(),
        joinedload(Series.player1).raiseload("*"),
        joinedload(Series.player2).raiseload("*"),
    )
    with Session() as session:
        series = session.scalars(
            select(Series)
            .options(*options)
            .where(Series.id == league["series_played_id"])
        ).first()
        public = SeriesPublic.from_series(series)

    assert len(public.player1.w3c_stats) == STATS_PER_PLAYER
    assert len(public.player1.gnl_stats) == 1
    assert len(public.player1.signup_seasons) == 1
