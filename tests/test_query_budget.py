"""Pin how many statements one series, bets or career stats answer costs.

Series._eager_options, DraftSeries._eager_options,
FantasyBet.list_eager_options and
PlayerCareerStats.eager_options decide the count, and the count is a
constant: it does not grow with the number of w3c_stats, team_seasons or
season signups a player carries, nor with the number of career rows. A
lazy load added to the serialization raises the count and fails a test
here.

Two tests layer raiseload on the paths the options cover, so an
unintended lazy load on those paths raises instead of passing silently.

A series or bet answer also derives its points and its match score, which
costs two more statements: one for the score system of every match in the
answer, one for the sum of the series on that system. Both are constant.

A team answer derives its standings the same way, and the two statements it
adds do not grow with the number of teams in the answer.

A career answer derives its nine totals from two more statements, and loads
the players who hold no stored row from four. Neither part grows with the
number of players or of rows in the answer.
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
from app.models.player_career_stats import (
    PlayerCareerStats,
    PlayerCareerStatsPublic,
)
from app.models.relationships import DBUserSeasonSignup
from app.models.series import Series, SeriesPublic
from app.models.user import User
from app.models.w3c_stats import W3CStats
from app.services.draft_series import DraftSeriesService
from app.services.fantasy_bets import FantasyBetService
from app.services.player_career_stats import PlayerCareerStatsService
from app.services.series import SeriesService
from app.services.teams import TeamService

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


def test_get_series_costs_nine_statements(league: dict[str, Any]) -> None:
    service = SeriesService(user_app_service=None)
    with count_statements() as tally:
        series = service.get(league["series_played_id"])
    assert series.player1.w3c_stats
    assert tally[0] == 9


def test_search_for_season_costs_three_statements(league: dict[str, Any]) -> None:
    """The season list is reduced, so it needs no collection statements."""
    service = SeriesService(user_app_service=None)
    query = QueryUtil.parseQuery("player1_id > 0")
    with count_statements() as tally:
        series_list = service.searchForSeason(league["season_id"], query)
    assert len(series_list) == 2
    assert series_list[0].player1.name
    assert series_list[0].player1.w3c_stats == []
    assert tally[0] == 3


def test_user_season_stats_cost_two_statements(league: dict[str, Any]) -> None:
    """One statement for the counts and one for the matchup history."""
    service = SeriesService(user_app_service=None)
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

    service = SeriesService(user_app_service=None)
    with count_statements() as tally:
        series = service.get(league["series_played_id"])
    assert len(series.player1.w3c_stats) == 4 * STATS_PER_PLAYER
    assert tally[0] == 9


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


def test_fantasy_bets_list_costs_three_statements(league: dict[str, Any]) -> None:
    """The list carries no collection, so only the derived points add to it."""
    service = FantasyBetService()
    with count_statements() as tally:
        bets, total = service.getAll()
    assert len(bets) == 1
    assert total is None
    assert bets[0].user.w3c_stats == []
    assert tally[0] == 3


def test_career_stats_cost_ten_statements(league: dict[str, Any]) -> None:
    """Four for the stored rows and their players, two for the derived totals,
    four for the players who hold no row."""
    service = PlayerCareerStatsService()
    with count_statements() as tally:
        career, total = service.get_all()
    assert len(career) == 3
    assert total == 3
    assert career[0].user.w3c_stats
    assert tally[0] == 10


def test_career_statement_count_holds_when_the_players_grow(
    league: dict[str, Any],
) -> None:
    """Two more players in a played series and no row for either, the same ten
    statements."""
    with Session() as session:
        players = [
            User(
                name=f"Extra {index}",
                battleTag=f"E{index}#1",
                discordTag=f"e{index}",
                discordId=f"9{index}",
                race=Race.HU,
            )
            for index in range(2)
        ]
        session.add_all(players)
        session.flush()
        session.add(
            Series(
                match_id=league["match_id"],
                player1_id=players[0].id,
                player2_id=players[1].id,
                player1_score=2,
                player2_score=0,
                host_player_id=players[0].id,
            )
        )
        session.commit()

    service = PlayerCareerStatsService()
    with count_statements() as tally:
        career, total = service.get_all()
    assert len(career) == 5
    assert total == 5
    assert tally[0] == 10


def test_career_stats_cost_six_statements_when_every_player_holds_a_row(
    league: dict[str, Any],
) -> None:
    """No player is left without a row, so the players statement falls away."""
    with Session() as session:
        for index, user_id in enumerate(league["player_ids"][2:]):
            session.add(
                PlayerCareerStats(user_id=user_id, player_name=f"Extra {index}")
            )
        session.commit()

    service = PlayerCareerStatsService()
    with count_statements() as tally:
        career, total = service.get_all()
    assert len(career) == 4
    assert total == 4
    assert tally[0] == 6


def test_one_career_row_costs_six_statements(league: dict[str, Any]) -> None:
    """One row and its player, and the two statements of the derived totals."""
    service = PlayerCareerStatsService()
    with count_statements() as tally:
        stats = service.get_by_user_id(league["player_ids"][0])
    assert stats.series_won == 1
    assert tally[0] == 6


def add_teams_to_the_season(season_id: int, count: int) -> None:
    """More teams in the season, so a per-team fill would be visible."""
    from app.models.team import Team
    from app.models.team_season import DBTeamSeason

    with Session() as session:
        for index in range(count):
            team = Team(name=f"Extra {index}")
            session.add(team)
            session.flush()
            session.add(DBTeamSeason(team_id=team.id, season_id=season_id))
        session.commit()


def test_the_teams_of_a_season_cost_seven_statements(league: dict[str, Any]) -> None:
    """Five for the teams and their people, two for the standings."""
    service = TeamService(user_app_service=None)
    with count_statements() as tally:
        teams = service.get_teams_season(league["season_id"])
    assert len(teams) == 2
    assert teams[0].seasons_info[0].final_score is not None
    assert tally[0] == 7


def test_the_standings_count_holds_when_the_teams_grow(
    league: dict[str, Any],
) -> None:
    """Four more teams in the season, the same seven statements."""
    add_teams_to_the_season(league["season_id"], 4)

    service = TeamService(user_app_service=None)
    with count_statements() as tally:
        teams = service.get_teams_season(league["season_id"])
    assert len(teams) == 6
    assert tally[0] == 7


def test_career_options_cover_the_player_graph(league: dict[str, Any]) -> None:
    """raiseload on the user, so a lazy load off it raises.

    The wildcard covers the relationships of a player the options do not
    name, so dropping any of the four options fails this test.
    """
    options = (
        *PlayerCareerStats.eager_options(),
        joinedload(PlayerCareerStats.user).raiseload("*"),
    )
    with Session() as session:
        stats = session.scalars(
            select(PlayerCareerStats).options(*options).order_by(PlayerCareerStats.id)
        ).first()
        public = PlayerCareerStatsPublic.from_career_stats(stats)

    assert len(public.user.w3c_stats) == STATS_PER_PLAYER
    assert len(public.user.gnl_stats) == 1
    assert len(public.user.signup_seasons) == 1
