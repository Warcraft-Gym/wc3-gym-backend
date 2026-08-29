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

A user, a team roster or a full series answer also derives the season record of
every player it carries, which costs two more statements: one groups the series
of those players by season, one names the race of every opponent they met.
Neither grows with the number of players.

A career answer derives its nine totals from two more statements, and loads
the players who hold no stored row from one. Neither part grows with the
number of players or of rows in the answer, and a search over those rows
adds none.

A fantasy team answer derives its six score fields from four more statements:
the standings pair, one for the series of every season in the answer and one
for the bets of its captains. None of the four grows with the number of teams.
A bet result costs nothing, because the map scores of its series already ride
in the answer.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest
from fastapi import FastAPI
from sqlalchemy import event, select
from sqlalchemy.orm import joinedload

from app.core.db import Session, rel
from app.core.query import QueryUtil
from app.models.base import ident
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
from app.services import derived
from app.services.draft_series import DraftSeriesService
from app.services.fantasy_bets import FantasyBetService
from app.services.fantasy_teams import FantasyTeamService
from app.services.player_career_stats import PlayerCareerStatsService
from app.services.series import SeriesService
from app.services.teams import TeamService
from app.services.users import UserService

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


def test_get_series_costs_eleven_statements(league: dict[str, Any]) -> None:
    service = SeriesService()
    with count_statements() as tally:
        series = service.get(league["series_played_id"])
    assert series.player1 is not None
    assert series.player1.w3c_stats
    assert tally[0] == 11


def test_search_for_season_costs_three_statements(league: dict[str, Any]) -> None:
    """The season list is reduced, so it needs no collection statements."""
    service = SeriesService()
    query = QueryUtil.parse_query("player1_id > 0")
    with count_statements() as tally:
        series_list = service.search_for_season(league["season_id"], query)
    assert len(series_list) == 2
    assert series_list[0].player1 is not None
    assert series_list[0].player1.name
    assert series_list[0].player1.w3c_stats == []
    assert tally[0] == 3


def test_the_season_record_costs_two_statements(league: dict[str, Any]) -> None:
    """One statement for the counts and one for the matchup history, whether
    the answer holds one player or every player of the league."""
    service = UserService()
    users = [service.get(user_id) for user_id in league["player_ids"]]
    assert [len(user.gnl_stats) for user in users] == [1, 1, 1, 1]

    with Session() as session:
        with count_statements() as tally:
            derived.fill_gnl_stats(session, users[:1])
        assert tally[0] == 2
        with count_statements() as tally:
            derived.fill_gnl_stats(session, users)
        assert tally[0] == 2
    assert users[0].gnl_stats[0].games == 1


def test_draft_series_by_match_costs_seven_statements(league: dict[str, Any]) -> None:
    service = DraftSeriesService()
    with count_statements() as tally:
        draft_list = service.get_by_match_id(league["match_id"])
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

    service = SeriesService()
    with count_statements() as tally:
        series = service.get(league["series_played_id"])
    assert series.player1 is not None
    assert len(series.player1.w3c_stats) == 4 * STATS_PER_PLAYER
    assert tally[0] == 11


def test_options_cover_the_player_graph(league: dict[str, Any]) -> None:
    """raiseload on both players, so a lazy load there raises.

    The wildcard covers the relationships of a player the options do not
    name, so dropping any of the three player options fails this test.
    """
    options = (
        *Series._eager_options(),
        joinedload(rel(Series.player1)).raiseload("*"),
        joinedload(rel(Series.player2)).raiseload("*"),
    )
    with Session() as session:
        series = session.scalars(
            select(Series)
            .options(*options)
            .where(col(Series.id) == league["series_played_id"])
        ).first()
        assert series is not None
        public = SeriesPublic.from_series(series)

    assert public.player1 is not None
    assert len(public.player1.w3c_stats) == STATS_PER_PLAYER
    assert len(public.player1.gnl_stats) == 1
    assert len(public.player1.signup_seasons) == 1


def test_fantasy_bets_list_costs_three_statements(league: dict[str, Any]) -> None:
    """The list carries no collection, so only the derived points add to it.

    The bet result reads the map scores of the series the answer already
    carries, so it adds no statement of its own.
    """
    service = FantasyBetService()
    with count_statements() as tally:
        bets, total = service.get_all()
    assert len(bets) == 1
    assert total is None
    assert bets[0].bet_result == 10
    assert bets[0].user is not None
    assert bets[0].user.w3c_stats == []
    assert tally[0] == 3


def add_bets_to_the_season(seeded: dict[str, Any], count: int) -> None:
    """More bets in the season, so a per-bet fill would be visible."""
    from tests.seed import add_bets

    with Session() as session:
        add_bets(session, seeded, count)
        session.commit()


def test_the_bets_count_holds_when_the_bets_grow(league: dict[str, Any]) -> None:
    """Four more bets, the same three statements."""
    add_bets_to_the_season(league, 4)

    service = FantasyBetService()
    with count_statements() as tally:
        bets, _ = service.get_all()
    assert len(bets) == 5
    assert all(bet.bet_result == 10 for bet in bets)
    assert tally[0] == 3


from sqlmodel import col

from tests.seed import add_fantasy_teams


def test_the_fantasy_team_list_costs_six_statements(league: dict[str, Any]) -> None:
    """One count, one for the teams, two for the standings, one for the season's
    series and one for the captains' bets."""
    service = FantasyTeamService()
    with count_statements() as tally:
        teams, total = service.get_all()
    assert len(teams) == 1
    assert total == 1
    assert teams[0].total_points == 30
    assert tally[0] == 6


def test_the_fantasy_count_holds_when_the_teams_grow(league: dict[str, Any]) -> None:
    """Four more fantasy teams, the same six statements."""
    add_fantasy_teams(league, 4)

    service = FantasyTeamService()
    with count_statements() as tally:
        teams, total = service.get_all()
    assert len(teams) == 5
    assert total == 5
    assert tally[0] == 6


def test_the_fantasy_team_search_costs_five_statements(league: dict[str, Any]) -> None:
    """The season-scoped search the leaderboards call pays the same five."""
    add_fantasy_teams(league, 4)

    service = FantasyTeamService()
    query = QueryUtil.parse_query(f"season_id == {league['season_id']}")
    with count_statements() as tally:
        teams, total = service.search(query)
    assert len(teams) == 5
    assert total is None
    assert tally[0] == 5


def test_career_stats_cost_four_statements(league: dict[str, Any]) -> None:
    """One for the stored rows and their players, two for the derived totals,
    one for the players who hold no row."""
    service = PlayerCareerStatsService()
    with count_statements() as tally:
        career, total = service.get_all()
    assert len(career) == 3
    assert total == 3
    assert career[0].user is not None
    assert career[0].user.name
    assert tally[0] == 4


def test_a_searched_career_answer_costs_the_same_four_statements(
    league: dict[str, Any],
) -> None:
    """The search runs on the rows already in hand, so it adds no statement."""
    service = PlayerCareerStatsService()
    with count_statements() as tally:
        career, total = service.get_all(search="p1")
    assert [row.player_name for row in career] == ["P1"]
    assert total == 1
    assert tally[0] == 4


def test_career_statement_count_holds_when_the_players_grow(
    league: dict[str, Any],
) -> None:
    """Two more players in a played series and no row for either, the same four
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
                player1_id=ident(players[0]),
                player2_id=ident(players[1]),
                player1_score=2,
                player2_score=0,
                host_player_id=ident(players[0]),
            )
        )
        session.commit()

    service = PlayerCareerStatsService()
    with count_statements() as tally:
        career, total = service.get_all()
    assert len(career) == 5
    assert total == 5
    assert tally[0] == 4


def test_career_stats_cost_three_statements_when_every_player_holds_a_row(
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
    assert tally[0] == 3


def test_one_career_row_costs_three_statements(league: dict[str, Any]) -> None:
    """One row and its player, and the two statements of the derived totals."""
    service = PlayerCareerStatsService()
    with count_statements() as tally:
        stats = service.get_by_user_id(league["player_ids"][0])
    assert stats is not None
    assert stats.series_won == 1
    assert tally[0] == 3


def add_teams_to_the_season(season_id: int, count: int) -> None:
    """More teams in the season, so a per-team fill would be visible."""
    from app.models.team import Team
    from app.models.team_season import DBTeamSeason

    with Session() as session:
        for index in range(count):
            team = Team(name=f"Extra {index}")
            session.add(team)
            session.flush()
            session.add(DBTeamSeason(team_id=ident(team), season_id=season_id))
        session.commit()


def test_the_teams_of_a_season_cost_seven_statements(league: dict[str, Any]) -> None:
    """Three for the teams and their people, two for the standings and two for
    the season record of every player."""
    service = TeamService(UserService())
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

    service = TeamService(UserService())
    with count_statements() as tally:
        teams = service.get_teams_season(league["season_id"])
    assert len(teams) == 6
    assert tally[0] == 7


def test_career_options_cover_the_player_graph(league: dict[str, Any]) -> None:
    """raiseload on the user, so a lazy load off it raises.

    The wildcard covers every relationship of a player, so a career row that
    reads one fails this test.
    """
    options = (
        *PlayerCareerStats.eager_options(),
        joinedload(rel(PlayerCareerStats.user)).raiseload("*"),
    )
    with Session() as session:
        stats = session.scalars(
            select(PlayerCareerStats)
            .options(*options)
            .order_by(col(PlayerCareerStats.id))
        ).first()
        assert stats is not None
        public = PlayerCareerStatsPublic.from_career_stats(stats)

    assert public.user is not None
    assert public.user.name
    assert public.user.race
    assert not hasattr(public.user, "w3c_stats")


def test_the_user_list_costs_three_statements(league: dict[str, Any]) -> None:
    """The count, the users with their W3C rows, and one statement for every
    signup on the page. A signup read per user cost one round trip each."""
    service = UserService()
    with count_statements() as tally:
        users, total = service.get_all(limit=50)
    assert total == len(users) == len(league["player_ids"])
    assert all(len(user.signup_seasons) == 1 for user in users)
    assert tally[0] == 3
