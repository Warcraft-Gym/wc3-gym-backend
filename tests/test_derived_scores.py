"""The series points and the match scores come from the map scores.

The write path still fills player1_points, player2_points, team1_score and
team2_score, so a response equals a direct read of those columns whenever the
two paths run on the same score system. That equality is the proof the derived
rule is the stored rule.

The systems part ways on purpose: the read path takes the system off the season
and the write path off the global score_system setting, so a helpstone season
under a standard setting reads 4 points for a sweep and stores 3. The last two
tests pin that, and the write path is the one that is wrong.
"""

from typing import Any

import pytest
from httpx2 import Client

from app.core.db import Session
from app.models.match import Match
from app.models.series import Series
from app.models.settings import Settings

# The five results a series can carry, as (player1_score, player2_score).
RESULTS = [(2, 0), (2, 1), (1, 2), (0, 2), (None, None)]


def post(
    client: Client, headers: dict[str, str], path: str, body: dict[str, Any]
) -> dict[str, Any]:
    resp = client.post(path, json=body, headers=headers)
    assert resp.status_code in (200, 201), (path, resp.status_code, resp.text)
    return resp.json()


def get(client: Client, path: str) -> Any:  # noqa: ANN401  # a JSON body
    resp = client.get(path)
    assert resp.status_code == 200, (path, resp.status_code, resp.text)
    return resp.json()


def set_score_system(system: str) -> None:
    """The setting the write path reads."""
    with Session() as session:
        session.add(Settings(key="score_system", value=system))
        session.commit()


def build_season(
    client: Client, headers: dict[str, str], name: str, system: str
) -> dict[str, Any]:
    """One season on the given system, with one match of five series."""
    season = post(
        client,
        headers,
        "/seasons",
        {
            "name": name,
            "number_weeks": 2,
            "series_per_week": 5,
            "score_system": system,
        },
    )
    team1 = post(client, headers, "/teams", {"name": f"{name} one"})
    team2 = post(client, headers, "/teams", {"name": f"{name} two"})
    players = [
        post(
            client,
            headers,
            "/users",
            {
                "name": f"{name} p{index}",
                "battleTag": f"{name}{index}#1",
                "discordTag": f"{name}{index}",
                "discordId": f"{name}{index}",
                "race": "HU",
            },
        )
        for index in (1, 2)
    ]
    post(
        client,
        headers,
        f"/seasons/addTeams/{season['id']}",
        {"team_ids": [team1["id"], team2["id"]]},
    )
    for team, player in zip((team1, team2), players, strict=True):
        post(
            client,
            headers,
            f"/teams/addPlayers/{team['id']}/seasons/{season['id']}",
            {"player_ids": [player["id"]]},
        )

    match = post(
        client,
        headers,
        "/matches",
        {
            "team1_id": team1["id"],
            "team2_id": team2["id"],
            "season_id": season["id"],
            "playday": 1,
        },
    )
    series_ids = [
        post(
            client,
            headers,
            "/series",
            {
                "match_id": match["id"],
                "player1_id": players[0]["id"],
                "player2_id": players[1]["id"],
                "host_player_id": players[0]["id"],
                "player1_score": one,
                "player2_score": two,
            },
        )["id"]
        for one, two in RESULTS
    ]
    return {
        "season_id": season["id"],
        "match_id": match["id"],
        "series_ids": series_ids,
    }


def stored_series_points(series_id: int) -> tuple[int | None, int | None]:
    with Session() as session:
        series = session.get(Series, series_id)
        return series.player1_points, series.player2_points


def stored_match_score(match_id: int) -> tuple[int | None, int | None]:
    with Session() as session:
        match = session.get(Match, match_id)
        return match.team1_score, match.team2_score


# Parity. The season and the setting name the same system, so the two paths
# compute the same numbers and every response equals the stored column.


@pytest.mark.parametrize(
    "system,sweep,close", [("standard", 3, 2), ("helpstone", 4, 3)]
)
def test_the_answered_series_points_equal_the_stored_points(
    client: Client,
    auth_headers: dict[str, str],
    system: str,
    sweep: int,
    close: int,
) -> None:
    set_score_system(system)
    league = build_season(client, auth_headers, "Parity", system)

    expected = [(sweep, 0), (close, 1), (1, close), (0, sweep), (None, None)]
    for series_id, points in zip(league["series_ids"], expected, strict=True):
        series = get(client, f"/series/{series_id}")
        answered = (series["player1_points"], series["player2_points"])
        assert answered == points
        assert answered == stored_series_points(series_id)


@pytest.mark.parametrize("system", ["standard", "helpstone"])
def test_the_answered_match_score_equals_the_stored_score(
    client: Client, auth_headers: dict[str, str], system: str
) -> None:
    set_score_system(system)
    league = build_season(client, auth_headers, "Parity", system)

    match = get(client, f"/matches/{league['match_id']}")
    answered = (match["team1_score"], match["team2_score"])
    assert answered == stored_match_score(league["match_id"])
    # The five series pay the same total to both sides on either system.
    assert answered[0] == answered[1]


@pytest.mark.parametrize("system", ["standard", "helpstone"])
def test_the_series_list_answers_the_points_of_every_row(
    client: Client, auth_headers: dict[str, str], system: str
) -> None:
    set_score_system(system)
    league = build_season(client, auth_headers, "Parity", system)

    rows = get(client, f"/series/season/{league['season_id']}")
    assert len(rows) == len(RESULTS)
    for row in rows:
        answered = (row["player1_points"], row["player2_points"])
        assert answered == stored_series_points(row["id"])
        assert (row["match"]["team1_score"], row["match"]["team2_score"]) == (
            stored_match_score(league["match_id"])
        )


def test_an_unplayed_series_answers_no_points(
    client: Client, auth_headers: dict[str, str]
) -> None:
    set_score_system("standard")
    league = build_season(client, auth_headers, "Parity", "standard")

    series = get(client, f"/series/{league['series_ids'][-1]}")
    assert series["player1_score"] is None
    assert series["player1_points"] is None
    assert series["player2_points"] is None


# Two seasons on different systems. The setting is standard, so the read path
# and the write path agree on the first season and part ways on the second.


@pytest.fixture
def two_seasons(client: Client, auth_headers: dict[str, str]) -> dict[str, Any]:
    set_score_system("standard")
    return {
        "standard": build_season(client, auth_headers, "Std", "standard"),
        "helpstone": build_season(client, auth_headers, "Help", "helpstone"),
    }


def test_a_search_over_two_seasons_pays_each_row_by_its_own_season(
    client: Client, two_seasons: dict[str, Any]
) -> None:
    resp = client.post("/series/search", params={"query": "player1_id > 0"})
    assert resp.status_code == 200, resp.text
    rows = {row["id"]: row for row in resp.json()}
    assert len(rows) == 2 * len(RESULTS)

    # The sweep is the first result of each season, and it is the one the
    # two scales price differently.
    standard_sweep = rows[two_seasons["standard"]["series_ids"][0]]
    helpstone_sweep = rows[two_seasons["helpstone"]["series_ids"][0]]
    assert standard_sweep["player1_points"] == 3
    assert helpstone_sweep["player1_points"] == 4


def test_a_season_pays_by_its_own_system_and_not_by_the_setting(
    client: Client, two_seasons: dict[str, Any]
) -> None:
    """The write path is still on the setting, so the stored column says 3."""
    series_id = two_seasons["helpstone"]["series_ids"][0]

    assert get(client, f"/series/{series_id}")["player1_points"] == 4
    assert stored_series_points(series_id)[0] == 3


# Standings. A team stands at the sum of its derived series points, and the
# season pays series_per_week * number_weeks * the top of its own scale.


def standings(team: dict[str, Any], season_id: int) -> tuple[int, int, int]:
    """final_score, points_against and points_available of one season row."""
    info = next(i for i in team["seasons_info"] if i["season_id"] == season_id)
    return info["final_score"], info["points_against"], info["points_available"]


def test_a_season_with_no_match_stands_every_team_at_zero(
    client: Client, auth_headers: dict[str, str]
) -> None:
    season = post(
        client,
        auth_headers,
        "/seasons",
        {"name": "Empty", "number_weeks": 3, "series_per_week": 4},
    )
    teams = [
        post(client, auth_headers, "/teams", {"name": f"Empty {index}"})
        for index in (1, 2, 3)
    ]
    post(
        client,
        auth_headers,
        f"/seasons/addTeams/{season['id']}",
        {"team_ids": [team["id"] for team in teams]},
    )

    rows = get(client, f"/teams/season/{season['id']}")
    assert len(rows) == 3
    # 3 weeks * 4 series * 3 points, and no team has taken any of it
    for team in rows:
        assert standings(team, season["id"]) == (0, 0, 36)


def test_a_season_stands_on_the_scale_of_its_own_system(
    client: Client, two_seasons: dict[str, Any]
) -> None:
    """The setting is standard, so only the helpstone season pays 4 a sweep.

    The five series pay 3+2+1+0 to each side on the standard scale and
    4+3+1+0 on the helpstone one, off 2 weeks * 5 series * the top of that
    scale.
    """
    for system, expected in (("standard", (6, 6, 18)), ("helpstone", (8, 8, 24))):
        season_id = two_seasons[system]["season_id"]
        rows = get(client, f"/teams/season/{season_id}")
        assert len(rows) == 2
        for team in rows:
            assert standings(team, season_id) == expected
