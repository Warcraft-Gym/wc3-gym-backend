"""The fantasy scores come from the map scores at read time.

No column holds them, so these tests pin the answer: the six score fields of
every fantasy team and the result of every bet, on every route that answers
one, plus the key order of both shapes. A second league proves that every
fantasy team scores against the season it names.

The seeded leagues are built through the models, so no test setup depends on
the write API.
"""

from typing import Any

import pytest
from httpx2 import Client

from app.core.db import Session
from app.models.enums import Race
from app.models.fantasy_bet import FantasyBet
from app.models.fantasy_team import FantasyTeam
from app.models.match import Match
from app.models.relationships import DBFantasyTeamPlayer
from app.models.season import Season
from app.models.series import Series
from app.models.team import Team
from app.models.team_season import DBTeamSeason
from app.models.user import User

SCORE_FIELDS = (
    "player_points",
    "bench_points",
    "team_points",
    "race_points",
    "bet_points",
    "total_points",
)


def player(name: str, race: Race) -> User:
    return User(
        name=name,
        battleTag=f"{name}#1",
        discordTag=name.lower(),
        discordId=name,
        race=race,
    )


TEAM_KEYS = [
    "name",
    "season_id",
    "captain_id",
    "drafted_team_id",
    "player_points",
    "bench_points",
    "team_points",
    "race_points",
    "bet_points",
    "total_points",
    "id",
    "drafted_race",
    "season",
    "captain",
    "drafted_team",
    "drafted_players",
]

BET_KEYS = [
    "season_id",
    "series_id",
    "user_id",
    "winner_id",
    "bet_result",
    "id",
    "bet_points",
    "season",
    "series",
    "user",
    "winner",
]


def get(client: Client, path: str) -> Any:  # noqa: ANN401  # a JSON body
    resp = client.get(path)
    assert resp.status_code == 200, (path, resp.status_code, resp.text)
    return resp.json()


def post(client: Client, path: str) -> Any:  # noqa: ANN401  # a JSON body
    resp = client.post(path)
    assert resp.status_code == 200, (path, resp.status_code, resp.text)
    return resp.json()


@pytest.fixture
def league(client: Client) -> dict[str, Any]:
    """One season of two weeks: two teams, four players, three series of which
    one has no result, two fantasy teams with drafts, and three bets."""
    with Session() as session:
        season = Season(name="Derived", number_weeks=2, series_per_week=2)
        team1, team2 = Team(name="One"), Team(name="Two")
        players = [
            player("D1", Race.HU),
            player("D2", Race.OC),
            player("D3", Race.NE),
            player("D4", Race.UD),
        ]
        session.add_all([season, team1, team2, *players])
        session.flush()

        session.add_all(
            [
                DBTeamSeason(team_id=team1.id, season_id=season.id),
                DBTeamSeason(team_id=team2.id, season_id=season.id),
            ]
        )
        week1 = Match(
            team1_id=team1.id, team2_id=team2.id, season_id=season.id, playday=1
        )
        week2 = Match(
            team1_id=team1.id, team2_id=team2.id, season_id=season.id, playday=2
        )
        session.add_all([week1, week2])
        session.flush()

        sweep = Series(
            match_id=week1.id,
            player1_id=players[0].id,
            player2_id=players[2].id,
            player1_score=2,
            player2_score=0,
            host_player_id=players[0].id,
        )
        open_series = Series(
            match_id=week1.id,
            player1_id=players[1].id,
            player2_id=players[3].id,
            host_player_id=players[1].id,
        )
        close = Series(
            match_id=week2.id,
            player1_id=players[0].id,
            player2_id=players[2].id,
            player1_score=1,
            player2_score=2,
            host_player_id=players[0].id,
        )
        session.add_all([sweep, open_series, close])

        first = FantasyTeam(
            name="First",
            season_id=season.id,
            captain_id=players[0].id,
            drafted_team_id=team1.id,
            drafted_race=Race.HU,
        )
        second = FantasyTeam(
            name="Second",
            season_id=season.id,
            captain_id=players[1].id,
            drafted_team_id=team2.id,
            drafted_race=Race.OC,
        )
        session.add_all([first, second])
        session.flush()

        session.add_all(
            [
                DBFantasyTeamPlayer(fantasy_team_id=first.id, user_id=players[0].id),
                DBFantasyTeamPlayer(fantasy_team_id=first.id, user_id=players[1].id),
                DBFantasyTeamPlayer(fantasy_team_id=second.id, user_id=players[2].id),
                # Called right, called wrong, and called on a series with no result
                FantasyBet(
                    season_id=season.id,
                    series_id=sweep.id,
                    user_id=players[0].id,
                    winner_id=players[0].id,
                    bet_points=10,
                ),
                FantasyBet(
                    season_id=season.id,
                    series_id=close.id,
                    user_id=players[0].id,
                    winner_id=players[0].id,
                    bet_points=4,
                ),
                FantasyBet(
                    season_id=season.id,
                    series_id=open_series.id,
                    user_id=players[1].id,
                    winner_id=players[1].id,
                    bet_points=7,
                ),
            ]
        )
        session.commit()
        return {"season_id": season.id, "team_ids": [first.id, second.id]}


# Every route that answers a fantasy team or a bet pins the same numbers.

# D1 swept week 1 for 10 and lost week 2 for 4; D2's series has no result.
# D2 stands in a week 1 series and in none in week 2, so he benches once for 5.
# Team One took 3 off the sweep and 1 off the close loss. HU tops week 1 and NE
# tops week 2, so each takes 18. The right call pays 10, the wrong one costs 4,
# and the call on the open series pays nothing.
FIRST = (14, 5, 4, 18, 6, 47)
# Second drafts D3, who lost week 1 and won week 2, and never benches. Team Two
# took 2, OC tops no week, and its captain's only bet sits on the open series.
SECOND = (8, 0, 2, 0, 0, 10)
# The right call pays its stake, the wrong one costs it, the open series pays
# nothing at all
BET_RESULTS = [10, -4, None]


def scores(team: dict[str, Any]) -> tuple[int, ...]:
    return tuple(team[field] for field in SCORE_FIELDS)


def test_the_team_list_pays_every_team(client: Client, league: dict[str, Any]) -> None:
    teams = {team["name"]: team for team in get(client, "/fantasy/teams")}
    assert len(teams) == 2
    assert scores(teams["First"]) == FIRST
    assert scores(teams["Second"]) == SECOND


def test_the_team_search_pays_the_same_numbers(
    client: Client, league: dict[str, Any]
) -> None:
    found = post(
        client, f"/fantasy/teams/search?query=season_id == {league['season_id']}"
    )
    teams = {team["name"]: team for team in found}
    assert len(teams) == 2
    assert scores(teams["First"]) == FIRST
    assert scores(teams["Second"]) == SECOND


def test_the_paged_team_search_pays_the_same_numbers(
    client: Client, league: dict[str, Any]
) -> None:
    found = post(
        client,
        f"/fantasy/teams/search?query=season_id == {league['season_id']}"
        "&limit=1&offset=0",
    )
    assert len(found) == 1
    assert scores(found[0]) == FIRST


def test_one_team_pays_the_same_numbers(client: Client, league: dict[str, Any]) -> None:
    team = get(client, f"/fantasy/teams/{league['team_ids'][0]}")
    assert scores(team) == FIRST


def test_the_bets_answer_their_results(client: Client, league: dict[str, Any]) -> None:
    bets = get(client, "/fantasy/bets")
    assert [bet["bet_result"] for bet in bets] == BET_RESULTS

    found = post(
        client, f"/fantasy/bets/search?query=season_id == {league['season_id']}"
    )
    assert [bet["bet_result"] for bet in found] == BET_RESULTS

    one = get(client, f"/fantasy/bets/{bets[0]['id']}")
    assert one["bet_result"] == BET_RESULTS[0]


def test_the_field_order_is_unchanged(client: Client, league: dict[str, Any]) -> None:
    """The response keys, in order, so a model edit cannot reshuffle them."""
    assert list(get(client, "/fantasy/teams")[0]) == TEAM_KEYS
    assert list(get(client, "/fantasy/bets")[0]) == BET_KEYS


def test_the_calculate_route_is_gone(
    client: Client, auth_headers: dict[str, str], league: dict[str, Any]
) -> None:
    """No write refreshes the fantasy scores, because the reads compute them."""
    resp = client.post(
        f"/fantasy/season/{league['season_id']}/calculate/", headers=auth_headers
    )
    assert resp.status_code == 404
    paths = client.get("/openapi.json").json()["paths"]
    assert "/fantasy/season/{season_id}/calculate/" not in paths


def test_a_team_write_that_still_sends_the_scores_is_accepted(
    client: Client, auth_headers: dict[str, str], league: dict[str, Any]
) -> None:
    """An old client sends the dropped fields, and the answer ignores them."""
    resp = client.put(
        f"/fantasy/teams/{league['team_ids'][0]}",
        json={
            "name": "Renamed",
            "player_points": 9999,
            "bench_points": 9999,
            "team_points": 9999,
            "race_points": 9999,
            "bet_points": 9999,
            "total_points": 9999,
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["name"] == "Renamed"
    assert scores(body) == FIRST


def test_a_bet_write_that_still_sends_the_result_is_accepted(
    client: Client, auth_headers: dict[str, str], league: dict[str, Any]
) -> None:
    """The admin page sends bet_result: null on every bet it creates."""
    bet = get(client, "/fantasy/bets")[0]
    resp = client.post(
        "/fantasy/bets",
        json={
            "season_id": bet["season_id"],
            "series_id": bet["series_id"],
            "user_id": bet["winner_id"],
            "winner_id": bet["winner_id"],
            "bet_points": 3,
            "bet_result": None,
        },
        headers=auth_headers,
    )
    assert resp.status_code == 201, resp.text
    # The call is right, so the new bet pays its stake straight away
    assert resp.json()["bet_result"] == 3


# Two seasons. Every fantasy team scores against the season it names.


@pytest.fixture
def two_seasons(client: Client) -> dict[str, Any]:
    """Season A over two weeks and season B over one, one fantasy team each.

    A's captain calls his own series right, B's captain calls his wrong.
    """
    with Session() as session:
        season_a = Season(name="A", number_weeks=2, series_per_week=2)
        season_b = Season(name="B", number_weeks=1, series_per_week=1)
        team_a1, team_a2 = Team(name="A1"), Team(name="A2")
        team_b1, team_b2 = Team(name="B1"), Team(name="B2")
        pa1, pa2 = player("A one", Race.HU), player("A two", Race.OC)
        pb1, pb2 = player("B one", Race.NE), player("B two", Race.UD)
        session.add_all(
            [season_a, season_b, team_a1, team_a2, team_b1, team_b2, pa1, pa2, pb1, pb2]
        )
        session.flush()

        session.add_all(
            [
                DBTeamSeason(team_id=team_a1.id, season_id=season_a.id),
                DBTeamSeason(team_id=team_a2.id, season_id=season_a.id),
                DBTeamSeason(team_id=team_b1.id, season_id=season_b.id),
                DBTeamSeason(team_id=team_b2.id, season_id=season_b.id),
            ]
        )
        match_a = Match(
            team1_id=team_a1.id, team2_id=team_a2.id, season_id=season_a.id, playday=1
        )
        match_b = Match(
            team1_id=team_b1.id, team2_id=team_b2.id, season_id=season_b.id, playday=1
        )
        session.add_all([match_a, match_b])
        session.flush()

        series_a = Series(
            match_id=match_a.id,
            player1_id=pa1.id,
            player2_id=pa2.id,
            player1_score=2,
            player2_score=0,
            host_player_id=pa1.id,
        )
        series_b = Series(
            match_id=match_b.id,
            player1_id=pb1.id,
            player2_id=pb2.id,
            player1_score=2,
            player2_score=1,
            host_player_id=pb1.id,
        )
        session.add_all([series_a, series_b])

        fantasy_a = FantasyTeam(
            name="Fantasy A",
            season_id=season_a.id,
            captain_id=pa1.id,
            drafted_team_id=team_a1.id,
            drafted_race=Race.HU,
        )
        fantasy_b = FantasyTeam(
            name="Fantasy B",
            season_id=season_b.id,
            captain_id=pb1.id,
            drafted_team_id=team_b1.id,
            drafted_race=Race.NE,
        )
        session.add_all([fantasy_a, fantasy_b])
        session.flush()

        session.add_all(
            [
                DBFantasyTeamPlayer(fantasy_team_id=fantasy_a.id, user_id=pa1.id),
                DBFantasyTeamPlayer(fantasy_team_id=fantasy_b.id, user_id=pb1.id),
                FantasyBet(
                    season_id=season_a.id,
                    series_id=series_a.id,
                    user_id=pa1.id,
                    winner_id=pa1.id,
                    bet_points=10,
                ),
                FantasyBet(
                    season_id=season_b.id,
                    series_id=series_b.id,
                    user_id=pb1.id,
                    winner_id=pb2.id,
                    bet_points=7,
                ),
            ]
        )
        session.commit()
        return {"season_a": season_a.id, "season_b": season_b.id}


# Fantasy A over season A: a 2-0 pays 10, week 2 sits on the bench for 5,
# team A1 stands at 3, HU tops the only week for 18, the bet pays its 10.
FANTASY_A = (10, 5, 3, 18, 10, 46)
# Fantasy B over season B: a 2-1 pays 8, the season is one week so nobody
# sits, team B1 stands at 2, NE tops the only week for 18, the bet loses 7.
FANTASY_B = (8, 0, 2, 18, -7, 21)


def test_one_answer_pays_each_team_by_its_own_season(
    client: Client, two_seasons: dict[str, Any]
) -> None:
    """One list holds both seasons, and each row reads the season it names.

    The deleted calculate route could not do this: it took one season and
    scored every fantasy team of the league against it, so calculating season A
    stamped season-A weeks, season-A race table and season-A standings onto the
    teams of season B.
    """
    teams = {team["name"]: team for team in get(client, "/fantasy/teams")}
    assert scores(teams["Fantasy A"]) == FANTASY_A
    assert scores(teams["Fantasy B"]) == FANTASY_B


def test_a_season_scoped_search_pays_the_same_numbers(
    client: Client, two_seasons: dict[str, Any]
) -> None:
    for season, expected in (
        (two_seasons["season_a"], FANTASY_A),
        (two_seasons["season_b"], FANTASY_B),
    ):
        found = post(client, f"/fantasy/teams/search?query=season_id == {season}")
        assert len(found) == 1
        assert scores(found[0]) == expected
