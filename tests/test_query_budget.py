"""Pin how many statements one series, bets or career stats answer costs.

Series._eager_options, DraftSeries._eager_options, FantasyBet.loads,
the fantasy team loads and PlayerCareerStats.eager_options decide the
count, and the count is a constant: it does not grow with the number of
w3c_stats, team_seasons or season signups a player carries, nor with the
number of career rows. A lazy load added to the serialization raises the count
and fails a test here.

A single series, draft, bet or fantasy team read joins its players bare, then
reads them again with app.services.users.summary_loads: one statement for the
players, one for their team row in the read's event and one for their tags. A
write answers through the same read after its commit.

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

A team roster reads one event: app.services.teams.roster_loads bounds its
players, its captains and its row of the event, and the players and the
captains each pay two statements more, their team row in the event and their
tags. A roster write answers through the event team read after its commit.

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
on it; the bet list adds four, for the season, the series with its match, the
casts and the veto picks. None of the seven grows with the answer. Naming the W3C season
the summary reads costs one statement more, and a second one where no
`current_w3c_season` setting is stored.
"""

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import timedelta
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
from app.models.relationships import DBFantasyTeamPlayer, DBUserSeasonSignup
from app.models.season import Season
from app.models.series import Series, SeriesCreate, SeriesPublic, SeriesUpdate
from app.models.types import utcnow
from app.models.user import User
from app.models.w3c_stats import W3CStats
from app.services import derived
from app.services.draft_series import DraftSeriesService
from app.services.fantasy_bets import FantasyBetService
from app.services.fantasy_teams import FantasyTeamService
from app.services.maps import MapService
from app.services.matches import MatchService
from app.services.player_career_stats import PlayerCareerStatsService
from app.services.seasons import SeasonService
from app.services.series import SeriesService
from app.services.teams import TeamService
from app.services.users import UserService, summary_loads
from tests.test_fantasy_locks import schedule, score
from tests.test_player_session import member_session

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
    """The bet, its season, its series as the list row with its match, the
    casts, the veto picks, three for the four player summaries, and the
    derived points, signup races and season record of the series players. The
    season is its summary, so its maps stay unread."""
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


def test_fantasy_bets_list_costs_eight_statements(league: dict[str, Any]) -> None:
    """The list carries the casts and the veto picks of each series, and the
    derived points; the match rides joined on its series.

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
    assert tally[0] == 8


def add_bets_to_the_season(seeded: dict[str, Any], count: int) -> None:
    """More bets in the season, so a per-bet fill would be visible."""
    from tests.seed import add_bets

    with Session() as session:
        add_bets(session, seeded, count)
        session.commit()


def test_the_bets_count_holds_when_the_bets_grow(league: dict[str, Any]) -> None:
    """Four more bets, the same eight statements."""
    add_bets_to_the_season(league, 4)

    service = FantasyBetService()
    with count_statements() as tally:
        bets, _ = service.get_all()
    assert len(bets) == 5
    assert all(bet.bet_result == 10 for bet in bets)
    assert tally[0] == 8


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


def draft_two(league: dict[str, Any]) -> None:
    """P2 and P3 drafted into the seeded fantasy team, so a lazy load per
    member shows."""
    with Session.begin() as session:
        for user_id in league["player_ids"][1:3]:
            session.add(
                DBFantasyTeamPlayer(
                    fantasy_team_id=league["fantasy_team_id"], user_id=user_id
                )
            )


def open_the_season(league: dict[str, Any]) -> None:
    """No series scored or past its time, so a member may still write."""
    score(league["series_played_id"], None, None)
    schedule(league["series_played_id"], utcnow() + timedelta(days=1))


def test_one_fantasy_team_costs_fifteen_statements(
    client: Client, league: dict[str, Any]
) -> None:
    """The team with its drafted team and members, its season, three for the
    member summaries, the four of the scores, the signup races, two for the
    current W3C season, the ladder summary and two for the season record."""
    draft_two(league)
    with count_statements() as tally:
        response = client.get(f"/fantasy/teams/{league['fantasy_team_id']}")
    assert response.status_code == 200
    body = response.json()
    players = body["drafted_players"]
    assert len(players) == 2
    for player in (body["captain"], *players):
        assert player["record"]["season_id"] == league["season_id"]
        assert player["gnl_stats"] == [player["record"]]
        assert "signup_seasons" not in player
    assert tally[0] == 15
    assert int(response.headers["X-DB-Rows"]) <= 29 + ROWS_MARGIN


def test_an_owner_team_edit_reads_the_team_once(
    client: Client, league: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The owner check and the reseat check read the team row, and the write
    answers through the single read once; it built the team three times, at
    77 statements."""
    draft_two(league)
    open_the_season(league)
    headers = member_session(monkeypatch, "1", "p1")
    with count_statements() as tally:
        response = client.put(
            f"/fantasy/teams/{league['fantasy_team_id']}",
            json={"name": "Renamed"},
            headers=headers,
        )
    assert response.status_code == 200, response.text
    assert response.json()["name"] == "Renamed"
    assert tally[0] == 30
    assert int(response.headers["X-DB-Rows"]) <= 42 + ROWS_MARGIN


def test_adding_team_players_answers_through_the_read(
    client: Client, league: dict[str, Any], auth_headers: dict[str, str]
) -> None:
    """The write, then the fifteen of the single read, so the answer carries
    the ladder summary and the record the read carries."""
    draft_two(league)
    with count_statements() as tally:
        response = client.post(
            f"/fantasy/teams/{league['fantasy_team_id']}/players",
            json={"player_ids": [league["player_ids"][3]]},
            headers=auth_headers,
        )
    assert response.status_code == 200, response.text
    assert len(response.json()["drafted_players"]) == 3
    assert tally[0] == 20
    assert int(response.headers["X-DB-Rows"]) <= 40 + ROWS_MARGIN


def test_a_fantasy_registration_answers_once(
    client: Client,
    league: dict[str, Any],
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The captain's team is updated and its roster set in one transaction,
    then the single read answers once; it built the team four times, at 97
    statements."""
    season = league["season_id"]
    p1, p2, p3, _ = league["player_ids"]
    response = client.put(
        f"/events/{season}/fantasy/tiers",
        json={"cuts": [1100, 1300], "tiers": {str(p1): 1, str(p2): 2, str(p3): 3}},
        headers=auth_headers,
    )
    assert response.status_code == 204, response.text
    open_the_season(league)
    headers = member_session(monkeypatch, "1", "p1")
    team = {
        "season_id": season,
        "drafted_team_id": league["team_a_id"],
        "drafted_race": "HU",
        "player_ids": [p1, p2, p3],
    }
    with count_statements() as tally:
        response = client.post("/fantasy-team", json=team, headers=headers)
    assert response.status_code == 201, response.text
    body = response.json()
    assert body["id"] == league["fantasy_team_id"]
    assert {player["id"] for player in body["drafted_players"]} == {p1, p2, p3}
    assert tally[0] == 55
    assert int(response.headers["X-DB-Rows"]) <= 58 + ROWS_MARGIN


def test_one_bet_route_costs_the_single_read(
    client: Client, league: dict[str, Any]
) -> None:
    """The thirteen of the single read, with the auth of the request."""
    bet_id = client.get("/fantasy/bets").json()[0]["id"]
    with count_statements() as tally:
        response = client.get(f"/fantasy/bets/{bet_id}")
    assert response.status_code == 200
    assert response.json()["series"]["player1"]["record"] is not None
    assert tally[0] == 13
    assert int(response.headers["X-DB-Rows"]) <= 17 + ROWS_MARGIN


def test_an_admin_bet_answers_through_the_read(
    client: Client, league: dict[str, Any], auth_headers: dict[str, str]
) -> None:
    """The admin token, the settings, the write, then the thirteen of the
    single read."""
    players = league["player_ids"]
    bet = {
        "season_id": league["season_id"],
        "series_id": league["series_open_id"],
        "user_id": players[1],
        "winner_id": players[1],
        "bet_points": 10,
    }
    with count_statements() as tally:
        response = client.post("/fantasy/bets", json=bet, headers=auth_headers)
    assert response.status_code == 201, response.text
    assert tally[0] == 15
    assert int(response.headers["X-DB-Rows"]) <= 20 + ROWS_MARGIN


def test_a_public_bet_reads_rows_and_answers_once(
    client: Client, league: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The open check reads the series row and the caller check his id; the
    place and the edit each answer through the single bet read once. They
    built the whole series and the whole bet to check them, at 42 and 51
    statements."""
    headers = member_session(monkeypatch, "1", "p1")
    bet = {
        "series_id": league["series_open_id"],
        "winner_id": league["player_ids"][1],
        "bet_points": 10,
    }
    with count_statements() as tally:
        response = client.post("/fantasy-bet", json=bet, headers=headers)
    assert response.status_code == 201, response.text
    assert response.json()["season_id"] == league["season_id"]
    assert tally[0] == 26
    assert int(response.headers["X-DB-Rows"]) <= 28 + ROWS_MARGIN

    with count_statements() as tally:
        response = client.put(
            f"/fantasy-bet/{response.json()['id']}",
            json={"bet_points": 5},
            headers=headers,
        )
    assert response.status_code == 200, response.text
    assert response.json()["bet_points"] == 5
    assert tally[0] == 25
    assert int(response.headers["X-DB-Rows"]) <= 30 + ROWS_MARGIN


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


def test_the_teams_of_a_season_cost_thirteen_statements(
    league: dict[str, Any],
) -> None:
    """One for the teams with their roster, one for the captains, one for the
    players' team row in the event, one for their tags, two for the current
    W3C season, two for the standings, one for the name and league of every
    season, one for the signup race of every player and, on the finished
    season, the MMR he entered it with, and two for his season record."""
    service = TeamService(UserService())
    with count_statements() as tally:
        teams = service.get_teams_season(league["season_id"])
    assert len(teams) == 2
    assert teams[0].seasons_info[0].final_score is not None
    assert teams[0].seasons_info[0].name == "Season 1"
    assert tally[0] == 13


def test_the_standings_count_holds_when_the_teams_grow(
    league: dict[str, Any],
) -> None:
    """Four more teams in the season, the same thirteen statements."""
    add_teams_to_the_season(league["season_id"], 4)

    service = TeamService(UserService())
    with count_statements() as tally:
        teams = service.get_teams_season(league["season_id"])
    assert len(teams) == 6
    assert tally[0] == 13


def add_captains_and_a_second_season(league: dict[str, Any]) -> int:
    """Two captains of team A in the season, and a second season of the league
    in which team A fields two players and a captain. Returns that season's id."""
    from app.models.relationships import DBTeamSeasonCaptain
    from app.models.team_season import DBTeamSeason
    from app.models.user_team_season import DBUserTeamSeason

    team_id, players = league["team_a_id"], league["player_ids"]
    with Session.begin() as session:
        for user_id in players[:2]:
            session.add(
                DBTeamSeasonCaptain(
                    team_id=team_id, season_id=league["season_id"], user_id=user_id
                )
            )
        other = Season(
            name="Season 2", series_per_round=1, league_id=league["league_id"]
        )
        session.add(other)
        session.flush()
        other_id = ident(other)
        session.add(DBTeamSeason(team_id=team_id, season_id=other_id))
        for user_id in players[:2]:
            session.add(
                DBUserTeamSeason(user_id=user_id, team_id=team_id, season_id=other_id)
            )
        session.add(
            DBTeamSeasonCaptain(team_id=team_id, season_id=other_id, user_id=players[0])
        )
    return other_id


def test_an_event_team_costs_twenty_one_statements(league: dict[str, Any]) -> None:
    """Two for the event and the team, the thirteen of the season list, two for
    the captains' team row and tags, and four for the rounds its players sit
    out. The other season's rows stay unread: the roster, the captains and the
    records hold this event alone."""
    add_captains_and_a_second_season(league)
    service = TeamService(UserService())
    with count_statements() as tally:
        team = service.get_with_nested_users_by_season(
            league["team_a_id"], league["season_id"]
        )
    assert list(team.player_by_season) == [league["season_id"]]
    assert list(team.captains_by_season) == [league["season_id"]]
    assert [info.season_id for info in team.seasons_info] == [league["season_id"]]
    captains = team.captains_by_season[league["season_id"]]
    assert len(captains) == 2
    assert all(c.record and c.gnl_stats == [c.record] for c in captains)
    assert tally[0] == 21


def test_a_league_team_costs_five_statements(league: dict[str, Any]) -> None:
    """One for the team, one for its seasons, two for the standings and one for
    the season labels; no roster, captain or player is read."""
    add_captains_and_a_second_season(league)
    service = TeamService(UserService())
    with count_statements() as tally:
        team = service.get(league["team_a_id"], league["league_id"])
    assert len(team.seasons_info) == 2
    assert not hasattr(team, "player_by_season")
    assert tally[0] == 5


def test_a_roster_write_answers_through_the_event_read(
    client: Client, league: dict[str, Any], auth_headers: dict[str, str]
) -> None:
    """The players and the captains writes pay their own statements and the
    Discord role sync, then the twenty-one of the event team read after the
    commit: one event's roster, never every season's."""
    add_captains_and_a_second_season(league)
    path = f"/events/{league['season_id']}/teams/{league['team_a_id']}"
    with count_statements() as tally:
        response = client.post(
            f"{path}/players",
            json={"player_ids": [league["player_ids"][2]]},
            headers=auth_headers,
        )
    assert response.status_code == 200
    body = response.json()
    assert list(body["player_by_season"]) == [str(league["season_id"])]
    assert len(body["player_by_season"][str(league["season_id"])]) == 3
    assert tally[0] == 36
    assert int(response.headers["X-DB-Rows"]) <= 53 + ROWS_MARGIN

    with count_statements() as tally:
        response = client.put(
            f"{path}/captains",
            json={"captain_ids": [league["player_ids"][0]]},
            headers=auth_headers,
        )
    assert response.status_code == 200
    body = response.json()
    assert list(body["captains_by_season"]) == [str(league["season_id"])]
    assert body["discord_role_missing"] == []
    assert tally[0] == 45
    assert int(response.headers["X-DB-Rows"]) <= 69 + ROWS_MARGIN


def test_a_match_costs_three_statements(league: dict[str, Any]) -> None:
    """The match with its teams, season and map, and two for its score; the
    season is its summary, so neither its maps nor its rounds are read."""
    service = MatchService()
    with count_statements() as tally:
        match = service.get(league["match_id"])
    assert match.season is not None
    assert match.season.round_count == 4
    assert tally[0] == 3


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
    # One tag row per player
    "/events/{season_id}/teams": 34,
    "/events/{season_id}/teams/{team_a_id}": 30,
    "/leagues/{league_id}/teams/{team_a_id}": 8,
    "/matches/{match_id}": 3,
    # The drafted team is its summary, so no roster row is read
    "/fantasy/teams/{fantasy_team_id}": 14,
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
