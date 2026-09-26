"""Pin how many statements one series, bets or career stats answer costs.

Series._eager_options, DraftSeries._eager_options, FantasyBet.eager_options,
FantasyBet.list_eager_options and PlayerCareerStats.eager_options decide the
count, and the count is a constant: it does not grow with the number of
w3c_stats, team_seasons or season signups a player carries, nor with the
number of career rows. A lazy load added to the serialization raises the count
and fails a test here.

A single series, draft or bet read joins its players bare, then reads them
again with app.services.users.summary_loads: one statement for the players,
one for their team row in the read's event and one for their tags. A write
answers through the same read after its commit.

Two tests layer raiseload on the paths the options cover, so an
unintended lazy load on those paths raises instead of passing silently.

A series or bet answer also derives its points and its match score, which
costs two more statements: one for the score system of every match in the
answer, one for the sum of the series on that system. Both are constant.
It also names the race every player registered on for the season of its
match, one more statement that does not grow with the answer.

A reduced series list rates both sides on the race each row names. One
statement tells the running events of the answer from the finished ones.
The rows of the running events cost two more, three while the W3Champions
season setting is unset; each finished event costs one. Neither part grows
with the number of rows in the answer.

A team answer derives its standings the same way, and the two statements it
adds do not grow with the number of teams in the answer. One more statement
names the event and the league of every season the answer holds, and one more
the race every player on a roster registered on for the season of that roster.
Neither grows with the answer.

A user, a team roster or a full series answer also derives the season record of
every player it carries, which costs two more statements: one groups the series
of those players by season, one names the race of every opponent they met.
Neither grows with the number of players.

A user, a user list, a team roster or a full series answer names the current
W3C season and reads the ladder summary of all its players in one more
statement, one row per race; the season costs one statement, two where no
`current_w3c_season` setting is stored. A profile reads the stale races in one
more. A roster of
an event that is over carries the MMR every roster player entered it with on
the signup race statement, at no statement more.

A career list derives its totals, search, order and page in SQL. A single
stored career row filters its tally to the linked user and matching name.
Neither statement count grows with the number of players or career rows.

The season list reads the phase of every season it answers in one grouped
aggregate, so it does not grow with the number of seasons. Identifying the
caller behind a Discord account is one statement, not the whole player row.

A fantasy team answer derives its six score fields from four more statements:
the standings pair, one for the series of every season in the answer and one
for the bets of its captains. None of the four grows with the number of teams.
A bet result costs nothing, because the map scores of its series already ride
in the answer. A team that drafts players pays three more: one for the race
they registered on and two for their season record. None of the three grows
with the number of teams.

A relation a list answer reads with selectinload is one more statement, and it
is the trade these budgets pay for: a joined collection sends each parent row
once per child row, while a selectin statement reads every distinct row once.
The fantasy team list adds one for the season of the answer, one for the
drafted players' season stats and one for the ladder summary of every person
on it; the bet list adds four, for the season, the series, the match and the
match's season. None of the seven grows with the answer. Naming the W3C season
the summary reads costs one statement more, and a second one where no
`current_w3c_season` setting is stored.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

import pytest
from fastapi import FastAPI
from httpx2 import Client
from sqlalchemy import event, select
from sqlalchemy.orm import joinedload, raiseload

from app.core.db import Session, rel
from app.core.query import QueryUtil
from app.models.base import ident
from app.models.draft_series import DraftSeries, DraftSeriesCreate
from app.models.enums import Race
from app.models.event_entrant import EventEntrant
from app.models.fantasy_bet import FantasyBetCreate
from app.models.player_career_stats import (
    PlayerCareerStats,
    PlayerCareerStatsPublic,
)
from app.models.relationships import DBUserSeasonSignup
from app.models.season import Season
from app.models.series import Series, SeriesCreate, SeriesPublic, SeriesUpdate
from app.models.user import User
from app.models.w3c_stats import W3CStats
from app.services import derived
from app.services.draft_series import DraftSeriesService
from app.services.fantasy_bets import FantasyBetService
from app.services.fantasy_teams import FantasyTeamService
from app.services.maps import MapService
from app.services.player_career_stats import PlayerCareerStatsService
from app.services.seasons import SeasonService
from app.services.series import SeriesService
from app.services.teams import TeamService
from app.services.users import UserService, summary_loads

STATS_PER_PLAYER = 8


@contextmanager
def count_statements() -> Iterator[list[int]]:
    """Report how many statements the engine sent inside the block.

    The egress ledger write after each request is not the route's own cost,
    so it is left out."""
    with Session() as session:
        engine = session.get_bind()
    tally = [0]

    def on_execute(conn: object, cursor: object, statement: str, *args: object) -> None:
        if "egress_ledger" not in statement:
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
                DBUserSeasonSignup(
                    user_id=user_id, season_id=seeded["season_id"], race=Race.HU
                )
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


def test_get_series_costs_fourteen_statements(league: dict[str, Any]) -> None:
    service = SeriesService()
    with count_statements() as tally:
        series = service.get(league["series_played_id"])
    assert series.player1 is not None
    assert series.player1.race_mmrs
    assert series.player1.record is not None
    assert series.player1.record.season_id == league["season_id"]
    assert series.player1.gnl_stats == [series.player1.record]
    assert tally[0] == 14


def test_search_for_season_costs_seven_statements(league: dict[str, Any]) -> None:
    """The season list is reduced: one statement for the casts, one for the pick
    steps, none per player and none per series. A GNL series reads its rules
    off the season its fixture loads, so the rules cost no statement.

    The reduced player carries no stats, so the list rates both sides of every
    row itself. The seeded season is finished: one statement finds that, and
    one reads the MMR of the time of every row.
    """
    service = SeriesService()
    query = QueryUtil.parse_query("player1_id > 0")
    with count_statements() as tally:
        series_list = service.search_for_season(league["season_id"], query)
    assert len(series_list) == 2
    assert series_list[0].player1 is not None
    assert series_list[0].player1.name
    assert series_list[0].player1.race_mmrs == []
    # one read finds the finished season, one reads the MMR of the time
    assert tally[0] == 7


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


def test_draft_series_by_match_costs_five_statements(league: dict[str, Any]) -> None:
    """The drafts, three for the player summaries and one for the signup races."""
    service = DraftSeriesService()
    with count_statements() as tally:
        draft_list = service.get_by_match_id(league["match_id"])
    assert len(draft_list) == 1
    assert draft_list[0].player1 is not None
    assert draft_list[0].player1.record is not None
    assert tally[0] == 5


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
    # one summary row per race, whatever the history holds
    assert len(series.player1.race_mmrs) == 1
    assert tally[0] == 14


def test_a_series_write_answers_through_the_read(league: dict[str, Any]) -> None:
    """A write pays its own statements, then the fourteen of the single read
    after its commit, so the answer carries what GET /series/{id} carries."""
    players = league["player_ids"]
    service = SeriesService()
    create = SeriesCreate(
        match_id=league["match_id"],
        player1_id=players[0],
        player2_id=players[1],
        host_player_id=players[0],
    )
    with count_statements() as tally:
        added = service.add(create)
    assert added.player1 is not None
    assert added.player1.record is not None
    assert added.player1.race_mmrs
    assert tally[0] == 21

    with count_statements() as tally:
        updated = service.update(
            league["series_open_id"], SeriesUpdate(host_player_id=players[1])
        )
    assert updated.player2 is not None
    assert updated.player2.record is not None
    assert tally[0] == 24


def test_a_draft_write_answers_through_the_read(league: dict[str, Any]) -> None:
    """The write and its fixture check, then the read of one draft."""
    players = league["player_ids"]
    create = DraftSeriesCreate(
        match_id=league["match_id"],
        player1_id=players[1],
        player2_id=players[2],
        host_player_id=players[1],
    )
    with count_statements() as tally:
        draft = DraftSeriesService().add(create)
    assert draft.player1 is not None
    assert draft.player1.record is not None
    assert tally[0] == 7


def test_one_bet_costs_thirteen_statements(league: dict[str, Any]) -> None:
    """The bet with its series, match and season, the casts, the veto steps,
    the season maps, three for the four player summaries, and the derived
    points, signup races and season record of the series players."""
    service = FantasyBetService()
    bets, _ = service.get_all()
    with count_statements() as tally:
        bet = service.get(bets[0].id)
    assert bet.user is not None
    assert bet.user.record is not None
    assert bet.series is not None
    assert bet.series.player1 is not None
    assert bet.series.player1.record is not None
    assert bet.series.player1.record.games == 1
    assert tally[0] == 13


def test_a_bet_write_answers_through_the_read(league: dict[str, Any]) -> None:
    """The settings, the write, then the thirteen of the single read."""
    players = league["player_ids"]
    create = FantasyBetCreate(
        season_id=league["season_id"],
        series_id=league["series_open_id"],
        user_id=players[1],
        winner_id=players[1],
        bet_points=10,
    )
    with count_statements() as tally:
        bet = FantasyBetService().add(create)
    assert bet.winner is not None
    assert bet.winner.record is not None
    assert tally[0] == 14


def test_the_entrants_read_costs_twelve_statements(
    client: Client, league: dict[str, Any]
) -> None:
    """Four reads of the event, the entrants, two for the current W3C season,
    the players, their team row in the event, their tags, their window W3C
    rows and the teams. The count does not grow with the number of entrants."""
    with Session.begin() as session:
        for user_id in league["player_ids"]:
            session.add(
                EventEntrant(
                    event_id=league["season_id"], user_id=user_id, race=Race.HU
                )
            )
    with count_statements() as tally:
        response = client.get(f"/events/{league['season_id']}/entrants")
    assert response.status_code == 200
    rows = response.json()
    assert len(rows) == len(league["player_ids"])
    assert all(row["user"]["record"]["season_id"] for row in rows)
    assert tally[0] == 12
    assert int(response.headers["X-DB-Rows"]) <= 28


def test_summary_loads_cover_the_player_graph(league: dict[str, Any]) -> None:
    """raiseload on both players, then their summary rows with raiseload again.

    The reload resets the loaders of each player, so it carries the wildcard
    too: a summary that reads a relationship summary_loads does not name
    fails this test.
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
        session.scalars(
            select(User)
            .options(*summary_loads(league["season_id"]), raiseload("*"))
            .where(col(User.id).in_((series.player1_id, series.player2_id)))
            .execution_options(populate_existing=True)
        ).all()
        public = SeriesPublic.from_series(series, league["season_id"])

    assert public.player1 is not None
    assert not hasattr(public.player1, "w3c_stats")
    assert not hasattr(public.player1, "signup_seasons")
    assert len(public.player1.gnl_stats) == 1
    assert len(public.player1.tags) == 1


def test_fantasy_bets_list_costs_ten_statements(league: dict[str, Any]) -> None:
    """The list carries the casts and the veto picks of each series, and the
    derived points.

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
    assert bets[0].user.race_mmrs == []
    assert tally[0] == 10


def add_bets_to_the_season(seeded: dict[str, Any], count: int) -> None:
    """More bets in the season, so a per-bet fill would be visible."""
    from tests.seed import add_bets

    with Session() as session:
        add_bets(session, seeded, count)
        session.commit()


def test_the_bets_count_holds_when_the_bets_grow(league: dict[str, Any]) -> None:
    """Four more bets, the same ten statements."""
    add_bets_to_the_season(league, 4)

    service = FantasyBetService()
    with count_statements() as tally:
        bets, _ = service.get_all()
    assert len(bets) == 5
    assert all(bet.bet_result == 10 for bet in bets)
    assert tally[0] == 10


from sqlmodel import col

from tests.seed import active, add_fantasy_teams


def test_the_fantasy_team_list_costs_ten_statements(league: dict[str, Any]) -> None:
    """One count, one for the teams, one for their season, two for the standings,
    one for the season's series, one for the captains' bets, two for the current
    W3C season and one for the ladder summary of the captain."""
    service = FantasyTeamService()
    with count_statements() as tally:
        teams, total = service.get_all()
    assert len(teams) == 1
    assert total == 1
    assert teams[0].total_points == 30
    assert tally[0] == 10


def test_the_fantasy_count_holds_when_the_teams_grow(league: dict[str, Any]) -> None:
    """Four more fantasy teams, each drafting a player, the same fourteen."""
    add_fantasy_teams(league, 4)

    service = FantasyTeamService()
    with count_statements() as tally:
        teams, total = service.get_all()
    assert len(teams) == 5
    assert total == 5
    assert tally[0] == 14


def test_the_fantasy_team_search_costs_thirteen_statements(
    league: dict[str, Any],
) -> None:
    """The season-scoped search the leaderboards call pays the list's fourteen
    less the count."""
    add_fantasy_teams(league, 4)

    service = FantasyTeamService()
    query = QueryUtil.parse_query(f"season_id == {league['season_id']}")
    with count_statements() as tally:
        teams, total = service.search(query)
    assert len(teams) == 5
    assert total is None
    assert tally[0] == 13


def test_career_stats_cost_two_statements(league: dict[str, Any]) -> None:
    """One reads the league seasons; one computes and pages the career rows."""
    service = PlayerCareerStatsService()
    with count_statements() as tally:
        career, total = service.get_all()
    assert len(career) == 3
    assert total == 3
    assert career[0].user is not None
    assert career[0].user.name
    assert tally[0] == 2


def test_a_searched_career_answer_costs_the_same_two_statements(
    league: dict[str, Any],
) -> None:
    """The search filters the SQL result without another statement."""
    service = PlayerCareerStatsService()
    with count_statements() as tally:
        career, total = service.get_all(search="p1")
    assert [row.player_name for row in career] == ["P1"]
    assert total == 1
    assert tally[0] == 2


def test_career_statement_count_holds_when_the_players_grow(
    league: dict[str, Any],
) -> None:
    """Two more players in a played series and no row for either, the same two
    statements."""
    with Session() as session:
        players = [
            User(
                name=f"Extra {index}",
                battle_tags=active(f"E{index}#1"),
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
    assert tally[0] == 2


def test_career_stats_cost_two_statements_when_every_player_holds_a_row(
    league: dict[str, Any],
) -> None:
    """Stored rows and played players share the paged query."""
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
    assert tally[0] == 2


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
        season = session.get_one(Season, season_id)
        assert season.league_id is not None
        for index in range(count):
            team = Team(name=f"Extra {index}", league_id=season.league_id)
            session.add(team)
            session.flush()
            session.add(DBTeamSeason(team_id=ident(team), season_id=season_id))
        session.commit()


def test_the_teams_of_a_season_cost_twelve_statements(
    league: dict[str, Any],
) -> None:
    """Four for the teams and their people, two for the current W3C season,
    two for the standings, one for the name and league of every season, one
    for the signup race of every player and, on the finished season, the MMR
    he entered it with, and two for his season record."""
    service = TeamService(UserService())
    with count_statements() as tally:
        teams = service.get_teams_season(league["season_id"])
    assert len(teams) == 2
    assert teams[0].seasons_info[0].final_score is not None
    assert teams[0].seasons_info[0].name == "Season 1"
    assert tally[0] == 12


def test_the_standings_count_holds_when_the_teams_grow(
    league: dict[str, Any],
) -> None:
    """Four more teams in the season, the same twelve statements."""
    add_teams_to_the_season(league["season_id"], 4)

    service = TeamService(UserService())
    with count_statements() as tally:
        teams = service.get_teams_season(league["season_id"])
    assert len(teams) == 6
    assert tally[0] == 12


def test_a_team_with_two_captains_costs_seven_statements(
    league: dict[str, Any],
) -> None:
    """One for the team and its captains, one for its seasons, one per captain
    for his season stats, two for the standings and one for the season labels;
    the captains' ladder rows and signups are never read."""
    from app.models.relationships import DBTeamSeasonCaptain

    team_id = league["team_a_id"]
    with Session.begin() as session:
        for user_id in league["player_ids"][:2]:
            session.add(
                DBTeamSeasonCaptain(
                    team_id=team_id, season_id=league["season_id"], user_id=user_id
                )
            )
    service = TeamService(UserService())
    with count_statements() as tally:
        team = service.get(team_id)
    captains = team.captains_by_season[league["season_id"]]
    assert len(captains) == 2
    assert all(not c.race_mmrs and not c.signup_seasons for c in captains)
    assert tally[0] == 7


def test_the_season_labels_cost_one_statement(league: dict[str, Any]) -> None:
    """One season or five, the tabs of a team page cost one read.

    The team page names its season tabs from seasons_info, so a per-season read
    here would be the N+1 the page used to pay with a second call.
    """
    from app.models.team_season import DBTeamSeason

    team_id = league["team_a_id"]
    service = TeamService(UserService())
    one = service.get(team_id)
    with Session() as session:
        with count_statements() as tally:
            derived.fill_season_labels(session, [one])
        assert tally[0] == 1

    with Session() as session:
        for index in range(4):
            season = Season(name=f"Season {index + 2}", series_per_round=1)
            session.add(season)
            session.flush()
            session.add(DBTeamSeason(team_id=team_id, season_id=ident(season)))
        session.commit()

    team = service.get(team_id)
    assert sorted(info.name or "" for info in team.seasons_info) == [
        f"Season {number}" for number in range(1, 6)
    ]
    assert team.seasons_info[0].league_short_name == "SL"
    with Session() as session:
        with count_statements() as tally:
            derived.fill_season_labels(session, [team])
        assert tally[0] == 1


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


def test_the_user_list_costs_seven_statements(league: dict[str, Any]) -> None:
    """The count, two for the current W3C season, the users, one statement for
    every signup on the page, one for every tag and one for the ladder summary
    of the page. A signup read per user cost one round trip each."""
    service = UserService()
    with count_statements() as tally:
        users, total = service.get_all(limit=50)
    assert total == len(users) == len(league["player_ids"])
    assert all(len(user.signup_seasons) == 1 for user in users)
    assert all(len(user.tags) == 1 for user in users)
    assert all(len(user.race_mmrs) == 1 for user in users)
    assert tally[0] == 7


def test_the_caller_lookup_costs_one_statement(league: dict[str, Any]) -> None:
    """A route that only identifies its caller reads the id, not the player's
    whole W3C history and every season he signed up for."""
    service = UserService()
    with count_statements() as tally:
        user_id = service.id_by_discord_id("1")
    assert user_id == league["player_ids"][0]
    assert tally[0] == 1


def test_the_season_list_costs_the_same_when_seasons_grow(
    league: dict[str, Any],
) -> None:
    """The phase of every season is one grouped aggregate, not one per season."""
    service = SeasonService(
        user_app_service=UserService(), map_app_service=MapService()
    )
    with count_statements() as tally:
        assert len(service.get_all()) == 1
    one_season = tally[0]

    with Session.begin() as session:
        for index in range(4):
            session.add(Season(name=f"Budget season {index}", series_per_round=1))

    with count_statements() as tally:
        seasons = service.get_all()
    assert len(seasons) == 5
    assert [season.phase for season in seasons[1:]] == ["open"] * 4
    assert tally[0] == one_season


# Rows one call of each route reads on the league fixture, as X-DB-Rows reports it
ROWS_PER_CALL = {
    # The players twice, joined and then with their summary rows; one tag row each
    "/series/{series_played_id}": 18,
    "/events/{season_id}/series": 11,
    "/fantasy/bets": 10,
    "/fantasy/teams": 10,
    "/stats/career": 4,
    "/stats/career/{player_id}": 3,
    "/events/{season_id}/teams": 30,
    "/events/{season_id}/teams/{team_a_id}": 28,
    # One tag row per player
    "/events/{season_id}/signups": 18,
    # One tag row per player
    "/users": 18,
    # One summary row per race, and one row naming the current W3C season
    "/users/{player_id}": 10,
    "/events": 8,
}
# Room for a row or two of drift before the ceiling fails
ROWS_MARGIN = 2


@pytest.mark.parametrize("route", sorted(ROWS_PER_CALL))
def test_rows_per_call_stay_under_the_ceiling(
    client: Client, league: dict[str, Any], route: str
) -> None:
    """A route that starts reading more rows per call fails here."""
    path = route.format(player_id=league["player_ids"][0], **league)
    response = client.get(path)
    assert response.status_code == 200
    assert int(response.headers["X-DB-Rows"]) <= ROWS_PER_CALL[route] + ROWS_MARGIN


def test_the_signups_read_costs_seven_statements(league: dict[str, Any]) -> None:
    """The season, two for the current W3C season, the signups with their users,
    one statement for the signups of those users with their seasons, one for
    their tags and one for their ladder summary. The count does not grow with
    the number of signups or seasons."""
    service = SeasonService(
        user_app_service=UserService(), map_app_service=MapService()
    )
    with Session.begin() as session:
        other = Season(name="Earlier season", series_per_round=1)
        session.add(other)
        session.flush()
        session.add(
            DBUserSeasonSignup(
                user_id=league["player_ids"][0], season_id=ident(other), race=Race.HU
            )
        )

    with count_statements() as tally:
        rows = service.get_signed_up_users(league["season_id"])
    assert len(rows) == len(league["player_ids"]) >= 3
    seasons = {row.id: len(row.signup_seasons) for row in rows}
    assert seasons.pop(league["player_ids"][0]) == 2
    assert set(seasons.values()) == {1}
    assert all(len(row.tags) == 1 for row in rows)
    assert tally[0] == 7
