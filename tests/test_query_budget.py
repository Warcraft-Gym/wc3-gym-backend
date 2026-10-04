"""Pin how many statements one series, bets or career stats answer costs.

Series._eager_options, DraftSeries._eager_options, FantasyBet.loads,
the fantasy team loads and PlayerCareerStats.eager_options decide the
count, and the count is a constant: it does not grow with the number of
w3c_stats, team_seasons or season signups a player carries, nor with the
number of career rows. A lazy load added to the serialization raises the count
and fails a test here. Each pin is a ceiling: a read that gets cheaper passes,
and its pin is lowered to the new count.

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
career row is the list's statement filtered to the user id. Neither statement
count grows with the number of players or career rows.

A player's summary read costs one statement: his name with a row per tag and
a row per race of his ladder summary. His seasons read costs three statements:
his seats with their team and signup, and the season record pair. His series
read costs two: the page as columns with its count, and the casts of the page.
None grows with the number of tags, races, seasons or series.

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

Every write route is pinned too: the tests above pin the series, draft, bet,
fantasy team and roster writes, and test_every_write_pins_its_statements pins
the rest on the seeded league, one request each after the rows it needs are
written. Every relationship refuses an on-the-spot load, so a read that needs
a relation its loader did not name raises in these tests instead of paying a
statement per row.
"""

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from datetime import timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from httpx2 import Client, Response
from sqlalchemy import event, select
from sqlalchemy.orm import joinedload, raiseload, selectinload

from app.core.db import Session, rel
from app.core.query import QueryUtil
from app.models.base import ident
from app.models.draft_series import DraftSeries, DraftSeriesCreate
from app.models.enums import Race
from app.models.event_entrant import EventEntrant
from app.models.fantasy_bet import FantasyBet, FantasyBetCreate
from app.models.map import Map
from app.models.player_career_stats import (
    PlayerCareerStats,
    PlayerCareerStatsPublic,
)
from app.models.relationships import (
    DBFantasyTeamPlayer,
    DBMapSeason,
    DBUserSeasonSignup,
)
from app.models.season import Season
from app.models.series import Series, SeriesCreate, SeriesPublic, SeriesUpdate
from app.models.types import utcnow
from app.models.user import User
from app.models.user_battle_tag import UserBattleTag
from app.models.w3c_stats import W3CStats
from app.services import derived, player_reads
from app.services.draft_series import DraftSeriesService
from app.services.fantasy_bets import FantasyBetService
from app.services.fantasy_teams import FantasyTeamService
from app.services.link_prompts import suggest
from app.services.maps import MapService
from app.services.matches import MatchService
from app.services.player_career_stats import PlayerCareerStatsService
from app.services.seasons import SeasonService
from app.services.series import SeriesService
from app.services.teams import TeamService
from app.services.users import UserService, summary_loads
from tests.test_auth import PNG
from tests.test_fantasy_locks import schedule, score
from tests.test_ffa import ffa, lobbies, play
from tests.test_mixed_fixture import (  # noqa: F401  # clan_war is a fixture
    clan_war,
    roster,
    template,
)
from tests.test_player_session import member_session
from tests.test_stage_engine import generate

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
    assert tally[0] <= 14


def test_search_for_season_costs_thirteen_statements(league: dict[str, Any]) -> None:
    """The season list is reduced: one statement each for the matches, their
    teams, seasons and players, the casts and the pick steps, none per series. A GNL series reads its rules
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
    assert tally[0] <= 13


def test_the_season_list_count_holds_when_the_series_grow(
    league: dict[str, Any],
) -> None:
    """Four more series on four more matches, the same statements: a to-one
    relation the list options miss would lazy-load once per row."""
    service = SeriesService()
    with count_statements() as tally:
        before = service.search_for_season(league["season_id"], None)
    add_bets_to_the_season(league, 4)
    with count_statements() as grown:
        after = service.search_for_season(league["season_id"], None)
    assert len(after) == len(before) + 4
    assert all(row.match is not None and row.match.team1 for row in after)
    assert grown[0] == tally[0]


def test_the_season_record_costs_two_statements(league: dict[str, Any]) -> None:
    """One statement for the counts and one for the matchup history, whether
    the answer holds one player or every player of the league."""
    service = UserService()
    users = [service.get(user_id) for user_id in league["player_ids"]]
    assert [len(user.gnl_stats) for user in users] == [1, 1, 1, 1]

    with Session() as session:
        with count_statements() as tally:
            derived.fill_gnl_stats(session, users[:1])
        assert tally[0] <= 2
        with count_statements() as tally:
            derived.fill_gnl_stats(session, users)
        assert tally[0] <= 2
    assert users[0].gnl_stats[0].games == 1


def test_draft_series_by_match_costs_five_statements(league: dict[str, Any]) -> None:
    """The drafts, three for the player summaries and one for the signup races."""
    service = DraftSeriesService()
    with count_statements() as tally:
        draft_list = service.get_by_match_id(league["match_id"])
    assert len(draft_list) == 1
    assert draft_list[0].player1 is not None
    assert draft_list[0].player1.record is not None
    assert tally[0] <= 5


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
    assert tally[0] <= 14


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
    assert tally[0] <= 21

    with count_statements() as tally:
        updated = service.update(
            league["series_open_id"], SeriesUpdate(host_player_id=players[1])
        )
    assert updated.player2 is not None
    assert updated.player2.record is not None
    assert tally[0] <= 24


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
    assert tally[0] <= 7


def test_one_bet_costs_nineteen_statements(league: dict[str, Any]) -> None:
    """The bet, its season, its series as the list row, its match, the teams,
    season and players of that row, the casts, the veto picks, three for the four player summaries, and the
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
    assert tally[0] <= 19


def test_a_bet_write_answers_through_the_read(league: dict[str, Any]) -> None:
    """The settings, the write, then the nineteen of the single read."""
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
    assert tally[0] <= 20


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
    assert tally[0] <= 12
    assert int(response.headers["X-DB-Rows"]) <= 28


def test_list_loads_cover_the_series_graph(league: dict[str, Any]) -> None:
    """raiseload under the match and both entrants of every list row: a relation
    the list answer reads that the list options do not name fails this test."""
    options = (
        *Series._list_eager_options(picks_only=True),
        selectinload(rel(Series.match)).raiseload("*"),
        selectinload(rel(Series.entrant1)).raiseload("*"),
        selectinload(rel(Series.entrant2)).raiseload("*"),
    )
    with Session() as session:
        rows = session.scalars(
            select(Series).options(*options).where(Series.in_event(league["season_id"]))
        ).all()
        public = [SeriesPublic.from_series(row) for row in rows]
    assert len(public) == 2
    assert all(row.match is not None for row in public)


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
    assert public.player1.record is not None
    assert len(public.player1.tags) == 1


def test_fantasy_bets_list_costs_fourteen_statements(league: dict[str, Any]) -> None:
    """The list carries the casts and the veto picks of each series, and the
    derived points; the match, its teams and season and the players each
    load once for the whole list.

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
    assert tally[0] <= 14


def add_bets_to_the_season(seeded: dict[str, Any], count: int) -> None:
    """More bets in the season, so a per-bet fill would be visible."""
    from tests.seed import add_bets

    with Session() as session:
        add_bets(session, seeded, count)
        session.commit()


def test_the_bets_count_holds_when_the_bets_grow(league: dict[str, Any]) -> None:
    """Four more bets, the same fourteen statements."""
    add_bets_to_the_season(league, 4)

    service = FantasyBetService()
    with count_statements() as tally:
        bets, _ = service.get_all()
    assert len(bets) == 5
    assert all(bet.bet_result == 10 for bet in bets)
    assert tally[0] <= 14


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
    assert tally[0] <= 10


def test_the_fantasy_count_holds_when_the_teams_grow(league: dict[str, Any]) -> None:
    """Four more fantasy teams, each drafting a player, the same fourteen."""
    add_fantasy_teams(league, 4)

    service = FantasyTeamService()
    with count_statements() as tally:
        teams, total = service.get_all()
    assert len(teams) == 5
    assert total == 5
    assert tally[0] <= 14


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
    assert tally[0] <= 13


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
        assert "gnl_stats" not in player
        assert "signup_seasons" not in player
    assert tally[0] <= 15
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
    assert tally[0] <= 30
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
    assert tally[0] <= 20
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
    assert tally[0] <= 55
    assert int(response.headers["X-DB-Rows"]) <= 58 + ROWS_MARGIN


def test_one_bet_route_costs_the_single_read(
    client: Client, league: dict[str, Any]
) -> None:
    """The nineteen of the single read, with the auth of the request."""
    bet_id = client.get("/fantasy/bets").json()[0]["id"]
    with count_statements() as tally:
        response = client.get(f"/fantasy/bets/{bet_id}")
    assert response.status_code == 200
    assert response.json()["series"]["player1"]["record"] is not None
    assert tally[0] <= 19
    assert int(response.headers["X-DB-Rows"]) <= 23 + ROWS_MARGIN


def test_an_admin_bet_answers_through_the_read(
    client: Client, league: dict[str, Any], auth_headers: dict[str, str]
) -> None:
    """The admin token, the settings, the write, then the nineteen of the
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
    assert tally[0] <= 21
    assert int(response.headers["X-DB-Rows"]) <= 26 + ROWS_MARGIN


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
    assert tally[0] <= 32
    assert int(response.headers["X-DB-Rows"]) <= 34 + ROWS_MARGIN

    with count_statements() as tally:
        response = client.put(
            f"/fantasy-bet/{response.json()['id']}",
            json={"bet_points": 5},
            headers=headers,
        )
    assert response.status_code == 200, response.text
    assert response.json()["bet_points"] == 5
    assert tally[0] <= 31
    assert int(response.headers["X-DB-Rows"]) <= 36 + ROWS_MARGIN


def test_career_stats_cost_two_statements(league: dict[str, Any]) -> None:
    """One reads the league seasons; one computes and pages the career rows."""
    service = PlayerCareerStatsService()
    with count_statements() as tally:
        career, total = service.get_all()
    assert len(career) == 3
    assert total == 3
    assert career[0].user is not None
    assert career[0].user.name
    assert tally[0] <= 2


def test_a_searched_career_answer_costs_the_same_two_statements(
    league: dict[str, Any],
) -> None:
    """The search filters the SQL result without another statement."""
    service = PlayerCareerStatsService()
    with count_statements() as tally:
        career, total = service.get_all(search="p1")
    assert [row.player_name for row in career] == ["P1"]
    assert total == 1
    assert tally[0] <= 2


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
    assert tally[0] <= 2


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
    assert tally[0] <= 2


def test_one_career_row_costs_two_statements(league: dict[str, Any]) -> None:
    """The league seasons, and the list's statement filtered to the user."""
    service = PlayerCareerStatsService()
    with count_statements() as tally:
        stats = service.get_by_user_id(league["player_ids"][0])
    assert stats is not None
    assert stats.series_won == 1
    assert tally[0] <= 2


def test_a_players_summary_costs_one_statement(league: dict[str, Any]) -> None:
    """The name, the current W3C season, the tags and the ladder races together."""
    with count_statements() as tally:
        summary = player_reads.summary(league["player_ids"][0])
    assert [row.race for row in summary.race_mmrs] == ["HU"]
    assert len(summary.tag_names) == 1
    assert tally[0] <= 1


def test_a_players_seasons_cost_three_statements(league: dict[str, Any]) -> None:
    """The seats with their team and signup, and the season record pair."""
    with count_statements() as tally:
        seasons = player_reads.seasons(league["player_ids"][0])
    assert [row.record.wins for row in seasons] == [1]
    assert tally[0] <= 3


def test_a_players_series_cost_two_statements(league: dict[str, Any]) -> None:
    """The page of series as columns with its count, and their casts."""
    with count_statements() as tally:
        rows, total = player_reads.series(
            league["player_ids"][0], [league["season_id"]]
        )
    assert [row.id for row in rows] == [league["series_played_id"]]
    assert total == 1
    assert tally[0] <= 2


def test_the_series_summary_costs_six_statements(
    client: Client, league: dict[str, Any]
) -> None:
    """Three for the event's cache phase, as the detail list pays them, then
    the season's score system and map rules, the page of series as columns and
    their casts."""
    with count_statements() as tally:
        response = client.get(f"/events/{league['season_id']}/series/summary")
    assert response.status_code == 200
    assert len(response.json()) == 2
    assert tally[0] <= 6


def test_the_series_summary_count_holds_when_the_series_grow(
    client: Client, league: dict[str, Any]
) -> None:
    """Four more series on four more matches, the same statements."""
    path = f"/events/{league['season_id']}/series/summary"
    with count_statements() as tally:
        before = client.get(path).json()
    add_bets_to_the_season(league, 4)
    with count_statements() as grown:
        after = client.get(path).json()
    assert len(after) == len(before) + 4
    assert grown[0] == tally[0]


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
    assert tally[0] <= 13


def test_the_standings_count_holds_when_the_teams_grow(
    league: dict[str, Any],
) -> None:
    """Four more teams in the season, the same thirteen statements."""
    add_teams_to_the_season(league["season_id"], 4)

    service = TeamService(UserService())
    with count_statements() as tally:
        teams = service.get_teams_season(league["season_id"])
    assert len(teams) == 6
    assert tally[0] <= 13


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
    assert all(c.record for c in captains)
    assert tally[0] <= 21


def test_a_league_team_costs_five_statements(league: dict[str, Any]) -> None:
    """One for the team, one for its seasons, two for the standings and one for
    the season labels; no roster, captain or player is read."""
    add_captains_and_a_second_season(league)
    service = TeamService(UserService())
    with count_statements() as tally:
        team = service.get(league["team_a_id"], league["league_id"])
    assert len(team.seasons_info) == 2
    assert not hasattr(team, "player_by_season")
    assert tally[0] <= 5


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
    assert tally[0] <= 36
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
    assert tally[0] <= 45
    assert int(response.headers["X-DB-Rows"]) <= 69 + ROWS_MARGIN


def test_a_match_costs_three_statements(league: dict[str, Any]) -> None:
    """The match with its teams, season and map, and two for its score; the
    season is its summary, so neither its maps nor its rounds are read."""
    service = MatchService()
    with count_statements() as tally:
        match = service.get(league["match_id"])
    assert match.season is not None
    assert match.season.round_count == 4
    assert tally[0] <= 3


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
        assert tally[0] <= 1

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
        assert tally[0] <= 1


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
    assert tally[0] <= 7


def test_the_caller_lookup_costs_one_statement(league: dict[str, Any]) -> None:
    """A route that only identifies its caller reads the id, not the player's
    whole W3C history and every season he signed up for."""
    service = UserService()
    with count_statements() as tally:
        user_id = service.id_by_discord_id("1")
    assert user_id == league["player_ids"][0]
    assert tally[0] <= 1


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
    assert tally[0] <= one_season


# Rows one call of each route reads on the league fixture, as X-DB-Rows reports it
ROWS_PER_CALL = {
    # The players twice, joined and then with their summary rows; one tag row each
    "/series/{series_played_id}": 18,
    # Each match, team, season and player row once, beside the series rows
    "/events/{season_id}/series": 19,
    # The event and its round tally, the season, the two series rows; no cast
    "/events/{season_id}/series/summary": 5,
    "/fantasy/bets": 14,
    "/fantasy/teams": 10,
    "/stats/career": 4,
    "/stats/career/{player_id}": 2,
    # One tag row and one race row
    "/users/{player_id}/summary": 2,
    # One seat row, one tally row, one matchup row
    "/users/{player_id}/seasons": 3,
    # One series row; the seeded series has no cast
    "/users/{player_id}/series?event_id={season_id}": 1,
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
    assert tally[0] <= 7


class Form(dict[str, str]):
    """A request body sent as a form, the way the report dialog posts it."""


class Upload(dict[str, tuple[str, bytes, str]]):
    """A request body sent as a multipart file upload."""


class Writer:
    """The ids and headers a write case builds its request from, and the rows
    the case needs written before the request it pins."""

    def __init__(
        self,
        client: Client,
        league: dict[str, Any],
        admin: dict[str, str],
        member: Callable[..., dict[str, str]],
        replay_uploaded: Callable[..., None],
    ) -> None:
        self.client, self.league, self.admin, self.member = (
            client,
            league,
            admin,
            member,
        )
        self.replay_uploaded = replay_uploaded
        self.p1, self.p2, self.p3, self.p4 = league["player_ids"]
        self.season, self.match = league["season_id"], league["match_id"]
        self.team_a, self.league_id = league["team_a_id"], league["league_id"]
        self.played, self.open = league["series_played_id"], league["series_open_id"]

    def send(
        self, method: str, url: str, body: object, headers: dict[str, str]
    ) -> Response:
        if isinstance(body, Form):
            return self.client.request(method, url, data=body, headers=headers)
        if isinstance(body, Upload):
            return self.client.request(method, url, files=body, headers=headers)
        return self.client.request(method, url, json=body, headers=headers)

    def made(self, method: str, url: str, body: object, headers: dict[str, str]) -> Any:  # noqa: ANN401  # a JSON body
        response = self.send(method, url, body, headers)
        assert response.status_code < 300, response.text
        return response.json() if response.content else None

    def tag(self) -> int:
        body = self.made("POST", "/users/me/tags", {"tag": "Alt#7777"}, self.member())
        return next(tag["id"] for tag in body["tags"] if tag["tag"] == "Alt#7777")

    def no_login(self) -> int:
        """A person from an earlier season, with no Discord login to stop a merge."""
        with Session.begin() as session:
            person = User(name="Old", discordId=None, race=Race.HU)
            session.add(person)
            session.flush()
            session.add(
                UserBattleTag(
                    user_id=ident(person),
                    tag="Older#1234",
                    source="sheet",
                    is_active=True,
                )
            )
            return ident(person)

    def prompt(self) -> int:
        with Session.begin() as session:
            person = session.get_one(User, self.no_login())
            suggest(session, person, "sheet", tag="p1#1111")
        return self.made("GET", "/users/me/prompts", None, self.member())[0]["id"]

    def user(self) -> int:
        body = {
            "name": "P5",
            "battleTag": "P5#5555",
            "discordTag": "p5",
            "discordId": "5",
            "race": "HU",
        }
        return self.made("POST", "/users", body, self.admin)["id"]

    def team(self) -> int:
        url = f"/leagues/{self.league_id}/teams"
        return self.made("POST", url, {"name": "Gamma"}, self.admin)["id"]

    def cast(self) -> int:
        body = {"channel_url": "twitch.tv/gnlcaster"}
        url = f"/series/{self.open}/casts"
        return self.made("POST", url, body, self.member("3"))[0]["id"]

    def draft(self) -> int:
        """The seeded draft of the match."""
        with Session() as session:
            return ident(session.scalars(select(DraftSeries)).one())

    def free_draft(self) -> int:
        """A draft the fixture has room to promote: the open series and the
        seeded draft make way."""
        self.made("DELETE", f"/series/{self.open}", None, self.admin)
        self.made("DELETE", f"/draft-series/{self.draft()}", None, self.admin)
        body = {
            "match_id": self.match,
            "player1_id": self.p2,
            "player2_id": self.p4,
            "host_player_id": self.p2,
        }
        return self.made("POST", "/draft-series", body, self.admin)["id"]

    def captain(self) -> dict[str, str]:
        url = f"/events/{self.season}/teams/{self.team_a}/captains"
        self.made("PUT", url, {"captain_ids": [self.p1]}, self.admin)
        return self.member()

    def no_checkin(self) -> dict[str, str]:
        """P1, in a season that takes no check-in, so every round is open."""
        with Session.begin() as session:
            session.get_one(Season, self.season).checkin_enabled = False
        return self.member()

    def zoned(self) -> dict[str, str]:
        """P1, with the timezone a block needs."""
        with Session.begin() as session:
            session.get_one(User, self.p1).timezone = "Europe/Berlin"
        return self.member()

    def block(self) -> int:
        body = {
            "label": "Work",
            "weekdays": 31,
            "start_local": "09:00",
            "end_local": "17:00",
        }
        return self.made("POST", "/player-blocks/repeating", body, self.zoned())["id"]

    def busy(self) -> int:
        body = {"label": "Holiday", "first_day": "2026-01-06", "last_day": "2026-01-08"}
        return self.made("POST", "/player-blocks/busy", body, self.zoned())["id"]

    def fantasy_team(self) -> int:
        body = {"name": "Night Owls", "season_id": self.season, "captain_id": self.p2}
        return self.made("POST", "/fantasy/teams", body, self.admin)["id"]

    def drafted(self) -> int:
        """The seeded fantasy team, with P1 drafted onto it."""
        team_id = self.league["fantasy_team_id"]
        url = f"/fantasy/teams/{team_id}/players"
        self.made("POST", url, {"player_ids": [self.p1]}, self.admin)
        return team_id

    def bet(self) -> int:
        with Session() as session:
            return ident(session.scalars(select(FantasyBet)).one())

    def public_bet(self) -> int:
        """P1's bet on the open series, which has not started."""
        body = {"series_id": self.open, "winner_id": self.p2, "bet_points": 10}
        return self.made("POST", "/fantasy-bet", body, self.member())["id"]

    def replay(self, *games: int) -> dict[str, str]:
        """P1, with a replay of those games of the played series in the bucket."""
        self.replay_uploaded(self.played, *games)
        return self.member()

    def moved(self) -> dict[str, str]:
        """P1, with game 1 of the played series confirmed."""
        headers = self.replay(1)
        self.made("PUT", f"/player-series/{self.played}/replays/1", None, headers)
        return headers

    def veto(self) -> int:
        """P2, side A of the open series, in a season with an order and a pool;
        answers the map P2 bans first."""
        with Session.begin() as session:
            season = session.get_one(Season, self.season)
            season.pick_ban = "Ban_A|Ban_B|Pick_A|Pick_B"
            season.map_rules = "fixed,loser,loser"
            maps = [Map(name=name, shortname=name) for name in ("EI", "TS", "LR", "AL")]
            session.add_all(maps)
            session.flush()
            session.add_all(
                DBMapSeason(map_id=ident(map), season_id=self.season, position=n)
                for n, map in enumerate(maps, start=1)
            )
            return ident(maps[0])


# A write case: the method, the path, the body and the headers of the request it pins
WriteCase = Callable[[Writer], tuple[str, str, object, dict[str, str]]]

WRITES: dict[str, tuple[WriteCase, int]] = {
    "POST /users": (
        lambda w: (
            "POST",
            "/users",
            {
                "name": "P6",
                "battleTag": "P6#6666",
                "discordTag": "p6",
                "discordId": "6",
                "race": "OC",
            },
            w.admin,
        ),
        15,
    ),
    "POST /users/me/tags": (
        lambda w: ("POST", "/users/me/tags", {"tag": "Alt#7777"}, w.member()),
        26,
    ),
    "POST /users/me/prompts/{prompt_id}": (
        lambda w: (
            "POST",
            f"/users/me/prompts/{w.prompt()}",
            {"accept": True},
            w.member(),
        ),
        112,
    ),
    "PUT /users/me/tags/{tag_id}/active": (
        lambda w: ("PUT", f"/users/me/tags/{w.tag()}/active", None, w.member()),
        21,
    ),
    "DELETE /users/me/tags/{tag_id}": (
        lambda w: ("DELETE", f"/users/me/tags/{w.tag()}", None, w.member()),
        22,
    ),
    "POST /users/{user_id}/tags/{tag_id}/move": (
        lambda w: (
            "POST",
            f"/users/{w.p1}/tags/{w.tag()}/move",
            {"to_user_id": w.p2},
            w.admin,
        ),
        22,
    ),
    "POST /users/{user_id}/merge": (
        lambda w: (
            "POST",
            f"/users/{w.no_login()}/merge",
            {"into_user_id": w.p3},
            w.admin,
        ),
        78,
    ),
    "PUT /users/{user_id}": (
        lambda w: ("PUT", f"/users/{w.p1}", {"country": "NL"}, w.admin),
        16,
    ),
    "DELETE /users/{user_id}": (
        lambda w: ("DELETE", f"/users/{w.user()}", None, w.admin),
        10,
    ),
    "PUT /users/{user_id}/ban": (
        lambda w: ("PUT", f"/users/{w.p1}/ban", None, w.admin),
        2,
    ),
    "DELETE /users/{user_id}/ban": (
        lambda w: ("DELETE", f"/users/{w.p1}/ban", None, w.admin),
        1,
    ),
    "POST /leagues/{league_id}/teams": (
        lambda w: ("POST", f"/leagues/{w.league_id}/teams", {"name": "Delta"}, w.admin),
        4,
    ),
    "PUT /leagues/{league_id}/teams/{team_id}": (
        lambda w: (
            "PUT",
            f"/leagues/{w.league_id}/teams/{w.team_a}",
            {"long_name": "Alpha Team"},
            w.admin,
        ),
        7,
    ),
    "POST /leagues/{league_id}/teams/{team_id}/image": (
        lambda w: (
            "POST",
            f"/leagues/{w.league_id}/teams/{w.team_a}/image",
            Upload(image=("icon.png", PNG, "image/png")),
            w.admin,
        ),
        2,
    ),
    "DELETE /leagues/{league_id}/teams/{team_id}": (
        lambda w: ("DELETE", f"/leagues/{w.league_id}/teams/{w.team()}", None, w.admin),
        6,
    ),
    "PUT /events/{event_id}/teams/{team_id}/availability": (
        lambda w: (
            "PUT",
            f"/events/{w.season}/teams/{w.team_a}/availability",
            {"user_id": w.p2, "playday": 1, "available": False},
            w.captain(),
        ),
        21,
    ),
    "PUT /events/{event_id}/teams/{team_id}/availability/all": (
        lambda w: (
            "PUT",
            f"/events/{w.season}/teams/{w.team_a}/availability/all",
            {"user_id": w.p2, "available": False},
            w.captain(),
        ),
        20,
    ),
    "DELETE /events/{event_id}/teams/{team_id}/players": (
        lambda w: (
            "DELETE",
            f"/events/{w.season}/teams/{w.team_a}/players",
            {"player_ids": [w.p2]},
            w.admin,
        ),
        33,
    ),
    "PUT /series/{series_id}/result-kind": (
        lambda w: (
            "PUT",
            f"/series/{w.open}/result-kind",
            {"result_kind": "walkover", "winner": 1},
            w.admin,
        ),
        23,
    ),
    "DELETE /series/{series_id}": (
        lambda w: ("DELETE", f"/series/{w.open}", None, w.admin),
        5,
    ),
    "POST /series/{series_id}/casts": (
        lambda w: (
            "POST",
            f"/series/{w.open}/casts",
            {"channel_url": "twitch.tv/gnlcaster"},
            w.member("3"),
        ),
        14,
    ),
    "PUT /series/{series_id}/casts/{cast_id}": (
        lambda w: (
            "PUT",
            f"/series/{w.open}/casts/{w.cast()}",
            {"channel_url": "twitch.tv/othercaster"},
            w.member("3"),
        ),
        9,
    ),
    "PUT /series/{series_id}/casts/{cast_id}/vod": (
        lambda w: (
            "PUT",
            f"/series/{w.open}/casts/{w.cast()}/vod",
            {"vod_url": "https://www.twitch.tv/videos/123"},
            w.member("3"),
        ),
        9,
    ),
    "DELETE /series/{series_id}/casts/{cast_id}": (
        lambda w: ("DELETE", f"/series/{w.open}/casts/{w.cast()}", None, w.member("3")),
        8,
    ),
    "PUT /draft-series/{draft_series_id}": (
        lambda w: (
            "PUT",
            f"/draft-series/{w.draft()}",
            {"host_player_id": w.p3},
            w.admin,
        ),
        15,
    ),
    "DELETE /draft-series/{draft_series_id}": (
        lambda w: ("DELETE", f"/draft-series/{w.draft()}", None, w.admin),
        8,
    ),
    "DELETE /draft-series/match/{match_id}": (
        lambda w: ("DELETE", f"/draft-series/match/{w.match}", None, w.admin),
        2,
    ),
    "POST /draft-series/{draft_series_id}/promote": (
        # the round check is one statement: the round size and the published count
        lambda w: ("POST", f"/draft-series/{w.free_draft()}/promote", None, w.admin),
        24,
    ),
    "PUT /draft-series/match/{match_id}/teams/{team_id}/ready": (
        lambda w: (
            "PUT",
            f"/draft-series/match/{w.match}/teams/{w.team_a}/ready",
            {"ready": True},
            w.captain(),
        ),
        21,
    ),
    "PUT /draft-series/match/{match_id}/teams/{team_id}/seen": (
        lambda w: (
            "PUT",
            f"/draft-series/match/{w.match}/teams/{w.team_a}/seen",
            None,
            w.captain(),
        ),
        16,
    ),
    "PUT /draft-series/match/{match_id}/max-mmr-difference": (
        lambda w: (
            "PUT",
            f"/draft-series/match/{w.match}/max-mmr-difference",
            {"max_mmr_difference": 250},
            w.captain(),
        ),
        22,
    ),
    "PUT /events/{event_id}/fantasy/tiers": (
        lambda w: (
            "PUT",
            f"/events/{w.season}/fantasy/tiers",
            {"cuts": [1100, 1300], "tiers": {str(w.p1): 1}},
            w.admin,
        ),
        5,
    ),
    "POST /fantasy/teams": (
        lambda w: (
            "POST",
            "/fantasy/teams",
            {"name": "Night Owls", "season_id": w.season, "captain_id": w.p2},
            w.admin,
        ),
        24,
    ),
    "DELETE /fantasy/teams/{team_id}": (
        lambda w: ("DELETE", f"/fantasy/teams/{w.fantasy_team()}", None, w.admin),
        3,
    ),
    "DELETE /fantasy/teams/{team_id}/players": (
        lambda w: (
            "DELETE",
            f"/fantasy/teams/{w.drafted()}/players",
            {"player_ids": [w.p1]},
            w.admin,
        ),
        18,
    ),
    "PUT /fantasy/bets/{bet_id}": (
        lambda w: ("PUT", f"/fantasy/bets/{w.bet()}", {"bet_points": 20}, w.admin),
        22,
    ),
    "DELETE /fantasy/bets/{bet_id}": (
        lambda w: ("DELETE", f"/fantasy/bets/{w.bet()}", None, w.admin),
        2,
    ),
    "POST /signup": (
        lambda w: (
            "POST",
            "/signup",
            {"name": "P9", "battleTag": "P9#1234", "race": "HU", "country": "DE"},
            w.member("99"),
        ),
        40,
    ),
    "PUT /player-availability": (
        lambda w: (
            "PUT",
            "/player-availability",
            {"playday": 2, "available": False},
            w.member(),
        ),
        22,
    ),
    "PUT /player-availability/all": (
        lambda w: (
            "PUT",
            "/player-availability/all",
            {"available": False},
            w.no_checkin(),
        ),
        21,
    ),
    "POST /player-blocks/repeating": (
        lambda w: (
            "POST",
            "/player-blocks/repeating",
            {
                "label": "Work",
                "weekdays": 31,
                "start_local": "09:00",
                "end_local": "17:00",
            },
            w.zoned(),
        ),
        17,
    ),
    "PUT /player-blocks/repeating/{block_id}": (
        lambda w: (
            "PUT",
            f"/player-blocks/repeating/{w.block()}",
            {"label": "Office"},
            w.member(),
        ),
        14,
    ),
    "DELETE /player-blocks/repeating/{block_id}": (
        lambda w: ("DELETE", f"/player-blocks/repeating/{w.block()}", None, w.member()),
        14,
    ),
    "POST /player-blocks/busy": (
        lambda w: (
            "POST",
            "/player-blocks/busy",
            {"label": "Holiday", "first_day": "2026-01-06", "last_day": "2026-01-08"},
            w.zoned(),
        ),
        17,
    ),
    "PUT /player-blocks/busy/{busy_id}": (
        lambda w: (
            "PUT",
            f"/player-blocks/busy/{w.busy()}",
            {"label": "Trip"},
            w.member(),
        ),
        14,
    ),
    "DELETE /player-blocks/busy/{busy_id}": (
        lambda w: ("DELETE", f"/player-blocks/busy/{w.busy()}", None, w.member()),
        14,
    ),
    "PUT /player-series/{series_id}": (
        lambda w: (
            "PUT",
            f"/player-series/{w.played}",
            Form(action="score_updated", player1_score="2", player2_score="0"),
            w.replay(1, 2),
        ),
        65,
    ),
    "POST /player-series/{series_id}/replays/{game_no}/upload-url": (
        lambda w: (
            "POST",
            f"/player-series/{w.played}/replays/1/upload-url",
            None,
            w.member(),
        ),
        31,
    ),
    "PUT /player-series/{series_id}/replays/{game_no}": (
        lambda w: ("PUT", f"/player-series/{w.played}/replays/2", None, w.replay(2)),
        33,
    ),
    "PUT /player-series/{series_id}/replays/{game_no}/move/{to_game}": (
        lambda w: (
            "PUT",
            f"/player-series/{w.played}/replays/1/move/2",
            None,
            w.moved(),
        ),
        34,
    ),
    "PUT /player-series/{series_id}/veto": (
        lambda w: (
            "PUT",
            f"/player-series/{w.open}/veto",
            {"action": "step", "map_id": w.veto()},
            w.member("2"),
        ),
        32,
    ),
    "PUT /user-info": (
        lambda w: ("PUT", "/user-info", {"twitch_url": "gnlcaster"}, w.member()),
        31,
    ),
    "DELETE /fantasy-bet/{bet_id}": (
        lambda w: ("DELETE", f"/fantasy-bet/{w.public_bet()}", None, w.member()),
        11,
    ),
}


@pytest.mark.parametrize("case", list(WRITES))
def test_every_write_pins_its_statements(
    client: Client,
    league: dict[str, Any],
    auth_headers: dict[str, str],
    member: Callable[..., dict[str, str]],
    replay_uploaded: Callable[..., None],
    monkeypatch: pytest.MonkeyPatch,
    case: str,
) -> None:
    """Each write route the tests above do not pin, on the seeded league: the
    statements of the one request, after the rows it needs are written. The
    W3Champions calls of a signup answer without the network."""
    monkeypatch.setattr(UserService, "validate_battle_tag", lambda self, tag: True)
    monkeypatch.setattr(UserService, "update_w3c_stats_by_id", lambda self, _: None)
    build, statements = WRITES[case]
    writer = Writer(client, league, auth_headers, member, replay_uploaded)
    method, url, body, headers = build(writer)
    with count_statements() as tally:
        response = writer.send(method, url, body, headers)
    assert response.status_code < 300, response.text
    assert tally[0] <= statements


def test_a_lobby_place_write_pins_its_statements(
    client: Client, auth_headers: dict[str, str]
) -> None:
    """PUT /series/{id}/places on the first lobby of a four player FFA: the
    write, the advance and the stage row it answers."""
    event, stage, _ = ffa(4)
    generate(client, auth_headers, event, stage)
    lobby = lobbies(client, event, stage)[0]
    with count_statements() as tally:
        response = play(client, auth_headers, lobby, [1, 2, 3, 4])
    assert response.status_code == 200, response.text
    assert tally[0] <= 16


def test_a_side_write_pins_its_statements(
    client: Client,
    auth_headers: dict[str, str],
    member: Callable[..., dict[str, str]],
    clan_war: dict[str, Any],  # noqa: F811  # the fixture imported above
) -> None:
    """PUT /series/{id}/sides by the captain of one clan, on the 2v2 of a
    clan war: the roster checks, the write and the stage row it answers."""
    pair = template(client, auth_headers, clan_war).json()[1]
    first, _ = clan_war["rosters"]
    captain = member(clan_war["captains"][0])
    with count_statements() as tally:
        response = roster(client, captain, pair["id"], 1, first[:2])
    assert response.status_code == 200, response.text
    assert tally[0] <= 33
