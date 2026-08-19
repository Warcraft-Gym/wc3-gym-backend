"""The fantasy scores come from the map scores at read time.

Two things are proven here. First that the read path answers what the stored
recalculation wrote: the whole body of every fantasy read matches, byte for
byte, the same body with the six stored columns pasted back in. Second that
every fantasy team now scores against the season it names, which the stored
path could not do.

The seeded leagues are built through the models, so no test setup depends on
the write API.
"""

import json
from typing import Any

import pytest
from httpx2 import Client
from sqlalchemy import select

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


def stored_team_scores() -> dict[int, dict[str, int | None]]:
    """The six columns the recalculation writes, straight off the table."""
    with Session() as session:
        rows = session.execute(
            select(
                FantasyTeam.id,
                FantasyTeam.player_points,
                FantasyTeam.bench_points,
                FantasyTeam.team_points,
                FantasyTeam.race_points,
                FantasyTeam.bet_points,
                FantasyTeam.total_points,
            )
        ).all()
    return {row[0]: dict(zip(SCORE_FIELDS, row[1:], strict=True)) for row in rows}


def stored_bet_results() -> dict[int, int | None]:
    """The bet_result column, straight off the table."""
    with Session() as session:
        rows = session.execute(select(FantasyBet.id, FantasyBet.bet_result)).all()
    return dict(rows)


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


# Parity. The recalculation writes the six columns, and the read path answers
# the same numbers without reading them.


@pytest.fixture
def calculated(
    client: Client, auth_headers: dict[str, str], league: dict[str, Any]
) -> dict[str, Any]:
    resp = client.post(
        f"/fantasy/season/{league['season_id']}/calculate/", headers=auth_headers
    )
    assert resp.status_code == 204, resp.text
    return league


def with_stored_scores(teams: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The same rows, with the six derived fields replaced by the columns.

    Replacing a key keeps its place, so the two bodies differ in nothing but
    the six values.
    """
    stored = stored_team_scores()
    return [{**team, **stored[team["id"]]} for team in teams]


def with_stored_results(bets: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The same rows, with bet_result replaced by the column."""
    stored = stored_bet_results()
    return [{**bet, "bet_result": stored[bet["id"]]} for bet in bets]


def test_the_team_list_answers_the_stored_numbers(
    client: Client, calculated: dict[str, Any]
) -> None:
    teams = get(client, "/fantasy/teams")
    assert len(teams) == 2
    assert json.dumps(teams) == json.dumps(with_stored_scores(teams))


def test_the_team_search_answers_the_stored_numbers(
    client: Client, calculated: dict[str, Any]
) -> None:
    teams = post(
        client,
        f"/fantasy/teams/search?query=season_id == {calculated['season_id']}",
    )
    assert len(teams) == 2
    assert json.dumps(teams) == json.dumps(with_stored_scores(teams))


def test_the_paged_team_search_answers_the_stored_numbers(
    client: Client, calculated: dict[str, Any]
) -> None:
    teams = post(
        client,
        f"/fantasy/teams/search?query=season_id == {calculated['season_id']}"
        "&limit=1&offset=0",
    )
    assert len(teams) == 1
    assert json.dumps(teams) == json.dumps(with_stored_scores(teams))


def test_one_team_answers_the_stored_numbers(
    client: Client, calculated: dict[str, Any]
) -> None:
    team = get(client, f"/fantasy/teams/{calculated['team_ids'][0]}")
    assert json.dumps([team]) == json.dumps(with_stored_scores([team]))


def test_the_bets_answer_the_stored_results(
    client: Client, calculated: dict[str, Any]
) -> None:
    bets = get(client, "/fantasy/bets")
    assert len(bets) == 3
    assert json.dumps(bets) == json.dumps(with_stored_results(bets))

    found = post(
        client, f"/fantasy/bets/search?query=season_id == {calculated['season_id']}"
    )
    assert len(found) == 3
    assert json.dumps(found) == json.dumps(with_stored_results(found))


def test_the_read_path_needs_no_recalculation(
    client: Client, league: dict[str, Any]
) -> None:
    """Nothing has run the calculate route, and the answer already stands."""
    with Session() as session:
        assert session.scalars(select(FantasyTeam.total_points)).all() == [None, None]

    teams = {team["name"]: team for team in get(client, "/fantasy/teams")}
    # D1 swept week 1 for 10 and lost week 2 for 4, D2's series has no result
    assert teams["First"]["player_points"] == 14
    # D2 stands in a week 1 series and in none in week 2, so he benches once
    assert teams["First"]["bench_points"] == 5
    # Team One took 3 off the sweep and 1 off the close loss
    assert teams["First"]["team_points"] == 4
    # HU tops week 1 and NE tops week 2, so each takes 18
    assert teams["First"]["race_points"] == 18
    # The right call pays 10, the wrong one costs 4, the open series pays nothing
    assert teams["First"]["bet_points"] == 6
    assert teams["First"]["total_points"] == 14 + 5 + 4 + 18 + 6


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
        return {
            "season_a": season_a.id,
            "season_b": season_b.id,
            "fantasy_b": fantasy_b.id,
        }


# Fantasy A over season A: a 2-0 pays 10, week 2 sits on the bench for 5,
# team A1 stands at 3, HU tops the only week for 18, the bet pays its 10.
FANTASY_A = (10, 5, 3, 18, 10, 46)
# Fantasy B over season B: a 2-1 pays 8, the season is one week so nobody
# sits, team B1 stands at 2, NE tops the only week for 18, the bet loses 7.
FANTASY_B = (8, 0, 2, 18, -7, 21)


def scores(team: dict[str, Any]) -> tuple[int, ...]:
    return tuple(team[field] for field in SCORE_FIELDS)


def test_one_answer_pays_each_team_by_its_own_season(
    client: Client, two_seasons: dict[str, Any]
) -> None:
    """One list holds both seasons, and each row reads the season it names.

    The stored path could not do this: calculateTeamScores took one season and
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


def test_calculating_one_season_does_not_move_the_other(
    client: Client, auth_headers: dict[str, str], two_seasons: dict[str, Any]
) -> None:
    """The recalculation of season A writes season-A numbers onto the team of
    season B, and the read path still answers season B."""
    resp = client.post(
        f"/fantasy/season/{two_seasons['season_a']}/calculate/", headers=auth_headers
    )
    assert resp.status_code == 204

    stored = stored_team_scores()[two_seasons["fantasy_b"]]
    # Two weeks on the bench for the one player, and nothing else pays
    assert tuple(stored[field] for field in SCORE_FIELDS) == (0, 10, 0, 0, 0, 10)

    team = get(client, f"/fantasy/teams/{two_seasons['fantasy_b']}")
    assert scores(team) == FANTASY_B
