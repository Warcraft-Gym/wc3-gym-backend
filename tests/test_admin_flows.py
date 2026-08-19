"""The write flows the admin frontend drives, through the API.

The league is built the way an administrator builds it: create the players and the
teams, put the teams in a season, fill the rosters, create the match and the series,
then enter a result.

Entering a result cascades. PUT /series/{id} converts the map score to points, rewrites
the per-player season stats, adds the series points into the match score, and rewrites
final_score, points_against and points_available on both team season rows. The
assertions walk that chain one step at a time.

Two tests are xfail(strict=True) on defects they pin. A fix turns them XPASS and fails
the run, so the marker goes with the fix.
"""

from typing import Any

import pytest
from httpx2 import Client

# The admin routes a season passes through, for the auth guard test.
GUARDED_WRITES = [
    ("POST", "/users"),
    ("PUT", "/users/1"),
    ("DELETE", "/users/1"),
    ("POST", "/teams"),
    ("PUT", "/teams/1"),
    ("DELETE", "/teams/1"),
    ("POST", "/seasons"),
    ("PUT", "/seasons/1"),
    ("DELETE", "/seasons/1"),
    ("POST", "/seasons/addTeams/1"),
    ("POST", "/seasons/removeTeams/1"),
    ("POST", "/teams/addPlayers/1/seasons/1"),
    ("POST", "/teams/removePlayers/1/seasons/1"),
    ("POST", "/matches"),
    ("PUT", "/matches/1"),
    ("DELETE", "/matches/1"),
    ("POST", "/series"),
    ("PUT", "/series/1"),
    ("DELETE", "/series/1"),
    ("POST", "/season/1/calculate/"),
]


def post(
    client: Client,
    headers: dict[str, str],
    path: str,
    body: dict[str, Any] | None = None,
) -> dict[str, Any]:
    resp = client.post(path, json=body or {}, headers=headers)
    assert resp.status_code in (200, 201), (path, resp.status_code, resp.text)
    return resp.json()


def put(
    client: Client, headers: dict[str, str], path: str, body: dict[str, Any]
) -> dict[str, Any]:
    resp = client.put(path, json=body, headers=headers)
    assert resp.status_code == 200, (path, resp.status_code, resp.text)
    return resp.json()


def get(client: Client, path: str) -> Any:  # noqa: ANN401  # a JSON body
    resp = client.get(path)
    assert resp.status_code == 200, (path, resp.status_code, resp.text)
    return resp.json()


def season_info(team: dict[str, Any], season_id: int) -> dict[str, Any]:
    """The team's row for one season, out of the seasons_info list."""
    for info in team["seasons_info"]:
        if info["season_id"] == season_id:
            return info
    raise AssertionError(f"team {team['id']} carries no info for season {season_id}")


def standings(
    client: Client, team_id: int, season_id: int
) -> tuple[int | None, int | None, int | None]:
    """final_score, points_against and points_available for one team."""
    info = season_info(get(client, f"/teams/{team_id}"), season_id)
    return info["final_score"], info["points_against"], info["points_available"]


def roster(client: Client, team_id: int, season_id: int) -> list[dict[str, Any]]:
    """The players of a team in a season.

    Read through /teams/{id}/seasons/{id}, because /teams/{id} answers an
    empty player_by_season - see test_a_team_on_its_own_carries_no_roster.
    """
    team = get(client, f"/teams/{team_id}/seasons/{season_id}")
    return team["player_by_season"].get(str(season_id), [])


@pytest.fixture
def league(client: Client, auth_headers: dict[str, str]) -> dict[str, Any]:
    """A season built entirely through the admin write endpoints.

    Two teams of one player each, one match on playday 1, one series with
    no result yet. Small on purpose: one series per team means the map
    score of that series is the whole standings table, so an assertion on
    a standings number names exactly one cause.
    """
    headers = auth_headers

    season = post(
        client,
        headers,
        "/seasons",
        {
            "name": "Admin Season",
            "number_weeks": 1,
            "series_per_week": 1,
            "start_date": "2026-03-02",
            "end_date": "2026-03-09",
        },
    )
    team_a = post(client, headers, "/teams", {"name": "AAA", "long_name": "Team AAA"})
    team_b = post(client, headers, "/teams", {"name": "BBB", "long_name": "Team BBB"})

    # HU and OC are the ids the admin frontend sends, from helpers/races.js.
    player_a = post(
        client,
        headers,
        "/users",
        {
            "name": "Ann",
            "battleTag": "Ann#1001",
            "discordTag": "ann",
            "discordId": "1001",
            "race": "HU",
            "mmr": 1500,
            "country": "DE",
        },
    )
    player_b = post(
        client,
        headers,
        "/users",
        {
            "name": "Bob",
            "battleTag": "Bob#1002",
            "discordTag": "bob",
            "discordId": "1002",
            "race": "OC",
            "mmr": 1450,
            "country": "US",
        },
    )

    post(
        client,
        headers,
        f"/seasons/addTeams/{season['id']}",
        {"team_ids": [team_a["id"], team_b["id"]]},
    )
    post(
        client,
        headers,
        f"/teams/addPlayers/{team_a['id']}/seasons/{season['id']}",
        {"player_ids": [player_a["id"]]},
    )
    post(
        client,
        headers,
        f"/teams/addPlayers/{team_b['id']}/seasons/{season['id']}",
        {"player_ids": [player_b["id"]]},
    )

    match = post(
        client,
        headers,
        "/matches",
        {
            "team1_id": team_a["id"],
            "team2_id": team_b["id"],
            "season_id": season["id"],
            "playday": 1,
        },
    )
    series = post(
        client,
        headers,
        "/series",
        {
            "match_id": match["id"],
            "player1_id": player_a["id"],
            "player2_id": player_b["id"],
            "host_player_id": player_a["id"],
        },
    )

    return {
        "season_id": season["id"],
        "team_a_id": team_a["id"],
        "team_b_id": team_b["id"],
        "player_a_id": player_a["id"],
        "player_b_id": player_b["id"],
        "match_id": match["id"],
        "series_id": series["id"],
    }


# Building the league. The fixture asserts a 200 or 201 on every create,
# so these read the rows back through the endpoints the frontend reads.


def test_a_created_player_is_in_the_list(
    client: Client, league: dict[str, Any]
) -> None:
    by_tag = {u["battleTag"]: u for u in get(client, "/users")}
    assert set(by_tag) == {"Ann#1001", "Bob#1002"}
    assert by_tag["Ann#1001"]["name"] == "Ann"
    assert by_tag["Ann#1001"]["race"] == "HU"
    assert by_tag["Ann#1001"]["mmr"] == 1500


def test_a_player_update_changes_only_its_fields(
    client: Client, auth_headers: dict[str, str], league: dict[str, Any]
) -> None:
    player_id = league["player_a_id"]
    put(client, auth_headers, f"/users/{player_id}", {"mmr": 1750})

    player = get(client, f"/users/{player_id}")
    assert player["mmr"] == 1750
    assert player["name"] == "Ann"
    assert player["battleTag"] == "Ann#1001"
    assert player["race"] == "HU"


def test_a_deleted_player_leaves_the_list(
    client: Client, auth_headers: dict[str, str], league: dict[str, Any]
) -> None:
    resp = client.delete(f"/users/{league['player_a_id']}", headers=auth_headers)
    assert resp.status_code == 204

    assert [u["battleTag"] for u in get(client, "/users")] == ["Bob#1002"]


def test_a_created_team_is_in_the_list(client: Client, league: dict[str, Any]) -> None:
    by_name = {t["name"]: t for t in get(client, "/teams")}
    assert set(by_name) == {"AAA", "BBB"}
    assert by_name["AAA"]["long_name"] == "Team AAA"


def test_a_team_update_changes_only_its_fields(
    client: Client, auth_headers: dict[str, str], league: dict[str, Any]
) -> None:
    team_id = league["team_a_id"]
    put(client, auth_headers, f"/teams/{team_id}", {"long_name": "Team A A A"})

    team = get(client, f"/teams/{team_id}")
    assert team["long_name"] == "Team A A A"
    assert team["name"] == "AAA"


def test_a_team_added_to_a_season_carries_that_season(
    client: Client, league: dict[str, Any]
) -> None:
    team = get(client, f"/teams/{league['team_a_id']}")
    assert [i["season_id"] for i in team["seasons_info"]] == [league["season_id"]]


def test_a_team_removed_from_a_season_drops_it(
    client: Client, auth_headers: dict[str, str], league: dict[str, Any]
) -> None:
    post(
        client,
        auth_headers,
        f"/seasons/removeTeams/{league['season_id']}",
        {"team_ids": [league["team_a_id"]]},
    )

    assert get(client, f"/teams/{league['team_a_id']}")["seasons_info"] == []


def test_a_player_added_to_a_team_is_on_its_roster(
    client: Client, league: dict[str, Any]
) -> None:
    players = roster(client, league["team_a_id"], league["season_id"])
    assert [u["battleTag"] for u in players] == ["Ann#1001"]


def test_a_player_removed_from_a_team_leaves_its_roster(
    client: Client, auth_headers: dict[str, str], league: dict[str, Any]
) -> None:
    post(
        client,
        auth_headers,
        f"/teams/removePlayers/{league['team_a_id']}/seasons/{league['season_id']}",
        {"player_ids": [league["player_a_id"]]},
    )

    assert roster(client, league["team_a_id"], league["season_id"]) == []


def test_a_team_on_its_own_carries_no_roster(
    client: Client, league: dict[str, Any]
) -> None:
    """GET /teams/{id} answers an empty player_by_season.

    The query behind it loads Team.user_seasons with noload("*"), so the link rows
    arrive without their user and the frontend reads the roster from
    /teams/{id}/seasons/{id} instead.
    """
    assert get(client, f"/teams/{league['team_a_id']}")["player_by_season"] == {}


def test_a_created_match_carries_both_teams(
    client: Client, league: dict[str, Any]
) -> None:
    match = get(client, f"/matches/{league['match_id']}")
    assert match["team1_id"] == league["team_a_id"]
    assert match["team2_id"] == league["team_b_id"]
    assert match["playday"] == 1


def test_a_created_series_carries_both_players(
    client: Client, league: dict[str, Any]
) -> None:
    series = get(client, f"/series/{league['series_id']}")
    assert series["player1_id"] == league["player_a_id"]
    assert series["player2_id"] == league["player_b_id"]
    assert series["match_id"] == league["match_id"]


def test_a_season_with_no_result_stands_at_nothing(
    client: Client, league: dict[str, Any]
) -> None:
    """A team season row starts empty, not at zero."""
    series = get(client, f"/series/{league['series_id']}")
    assert series["player1_score"] is None
    assert series["player1_points"] is None

    assert standings(client, league["team_a_id"], league["season_id"]) == (
        None,
        None,
        None,
    )


# Recording a result. On the standard scale a 2-0 win is worth 3 points, a
# 2-1 win 2 points, and the loser keeps its map score. points_available is
# series_per_week * number_weeks * 3, less the points both sides took, so
# in this one-series season it reaches 0 as soon as the series is played.


def test_a_recorded_result_sets_the_series_points(
    client: Client, auth_headers: dict[str, str], league: dict[str, Any]
) -> None:
    put(
        client,
        auth_headers,
        f"/series/{league['series_id']}",
        {"player1_score": 2, "player2_score": 1},
    )

    series = get(client, f"/series/{league['series_id']}")
    assert series["player1_score"] == 2
    assert series["player2_score"] == 1
    assert series["player1_points"] == 2
    assert series["player2_points"] == 1


def test_a_recorded_sweep_is_worth_three_points(
    client: Client, auth_headers: dict[str, str], league: dict[str, Any]
) -> None:
    put(
        client,
        auth_headers,
        f"/series/{league['series_id']}",
        {"player1_score": 2, "player2_score": 0},
    )

    series = get(client, f"/series/{league['series_id']}")
    assert series["player1_points"] == 3
    assert series["player2_points"] == 0


def test_a_recorded_result_moves_the_match_score(
    client: Client, auth_headers: dict[str, str], league: dict[str, Any]
) -> None:
    put(
        client,
        auth_headers,
        f"/series/{league['series_id']}",
        {"player1_score": 2, "player2_score": 1},
    )

    match = get(client, f"/matches/{league['match_id']}")
    assert match["team1_score"] == 2
    assert match["team2_score"] == 1


def test_a_recorded_result_moves_the_team_standings(
    client: Client, auth_headers: dict[str, str], league: dict[str, Any]
) -> None:
    put(
        client,
        auth_headers,
        f"/series/{league['series_id']}",
        {"player1_score": 2, "player2_score": 0},
    )

    season_id = league["season_id"]
    # The winner takes all three points of the only series in the season,
    # so neither side has anything left available.
    assert standings(client, league["team_a_id"], season_id) == (3, 0, 0)
    assert standings(client, league["team_b_id"], season_id) == (0, 3, 0)


def test_a_recorded_result_moves_the_player_season_stats(
    client: Client, auth_headers: dict[str, str], league: dict[str, Any]
) -> None:
    put(
        client,
        auth_headers,
        f"/series/{league['series_id']}",
        {"player1_score": 2, "player2_score": 0},
    )

    winner = roster(client, league["team_a_id"], league["season_id"])[0]
    stats = winner["gnl_stats"][0]
    assert (stats["games"], stats["wins"], stats["losses"]) == (1, 1, 0)

    loser = roster(client, league["team_b_id"], league["season_id"])[0]
    stats = loser["gnl_stats"][0]
    assert (stats["games"], stats["wins"], stats["losses"]) == (1, 0, 1)


def test_a_corrected_result_replaces_the_points_it_replaces(
    client: Client, auth_headers: dict[str, str], league: dict[str, Any]
) -> None:
    """A result entered wrongly and corrected must not be counted twice."""
    series_path = f"/series/{league['series_id']}"
    put(client, auth_headers, series_path, {"player1_score": 2, "player2_score": 0})
    put(client, auth_headers, series_path, {"player1_score": 1, "player2_score": 2})

    series = get(client, series_path)
    assert series["player1_points"] == 1
    assert series["player2_points"] == 2

    season_id = league["season_id"]
    assert standings(client, league["team_a_id"], season_id) == (1, 2, 0)
    assert standings(client, league["team_b_id"], season_id) == (2, 1, 0)


def test_a_corrected_result_replaces_the_player_record(
    client: Client, auth_headers: dict[str, str], league: dict[str, Any]
) -> None:
    series_path = f"/series/{league['series_id']}"
    put(client, auth_headers, series_path, {"player1_score": 2, "player2_score": 0})
    put(client, auth_headers, series_path, {"player1_score": 0, "player2_score": 2})

    stats = roster(client, league["team_a_id"], league["season_id"])[0]["gnl_stats"][0]
    assert (stats["games"], stats["wins"], stats["losses"]) == (1, 0, 1)


def test_a_deleted_series_takes_its_points_back(
    client: Client, auth_headers: dict[str, str], league: dict[str, Any]
) -> None:
    put(
        client,
        auth_headers,
        f"/series/{league['series_id']}",
        {"player1_score": 2, "player2_score": 0},
    )
    resp = client.delete(f"/series/{league['series_id']}", headers=auth_headers)
    assert resp.status_code == 204

    match = get(client, f"/matches/{league['match_id']}")
    assert match["team1_score"] == 0
    assert match["team2_score"] == 0
    assert standings(client, league["team_a_id"], league["season_id"]) == (0, 0, 3)


# The recalculation endpoint. The season page calls it, and it is the only
# thing that fills the standings after an import writes rows through the
# Session instead of through the API.


def test_the_recalculation_leaves_a_correct_season_alone(
    client: Client, auth_headers: dict[str, str], league: dict[str, Any]
) -> None:
    put(
        client,
        auth_headers,
        f"/series/{league['series_id']}",
        {"player1_score": 2, "player2_score": 1},
    )
    before = standings(client, league["team_a_id"], league["season_id"])

    resp = client.post(
        f"/season/{league['season_id']}/calculate/", headers=auth_headers
    )
    assert resp.status_code == 200

    assert standings(client, league["team_a_id"], league["season_id"]) == before


def test_the_recalculation_fills_standings_left_empty(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    """The seeded league holds a played 2-1 series and empty standings,
    which is the state an import leaves behind."""
    season_id = seeded["season_id"]
    assert standings(client, seeded["team_a_id"], season_id) == (None, None, None)

    resp = client.post(f"/season/{season_id}/calculate/", headers=auth_headers)
    assert resp.status_code == 200

    final_a, against_a, _ = standings(client, seeded["team_a_id"], season_id)
    final_b, against_b, _ = standings(client, seeded["team_b_id"], season_id)
    assert (final_a, against_a) == (2, 1)
    assert (final_b, against_b) == (1, 2)


def test_the_recalculation_keeps_the_series_points(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    """The seeded series is a 2-1, which is 2 points against 1."""
    season_id = seeded["season_id"]
    resp = client.post(f"/season/{season_id}/calculate/", headers=auth_headers)
    assert resp.status_code == 200

    series = get(client, f"/series/{seeded['series_played_id']}")
    assert (series["player1_points"], series["player2_points"]) == (2, 1)


def test_the_recalculation_reports_that_it_finished(
    client: Client, auth_headers: dict[str, str], league: dict[str, Any]
) -> None:
    season_id = league["season_id"]
    resp = client.post(f"/season/{season_id}/calculate/", headers=auth_headers)
    assert resp.status_code == 200

    status = get(client, f"/season/{season_id}/calculate/status")
    assert status["status"] == "completed"
    assert status["progress"] == 100


@pytest.mark.parametrize("method,path", GUARDED_WRITES)
def test_a_write_without_a_token_is_refused(
    client: Client, league: dict[str, Any], method: str, path: str
) -> None:
    resp = client.request(method, path)
    assert resp.status_code == 401


# The race column. The five members are RANDOM, HU, OC, NE and UD, and
# the input models take a Race, so pydantic answers 422 for anything else.
# The field used to be Race | str, which let any string through to a
# column the database reads back as an enum, and one such row made
# GET /users answer 500 for every caller.


@pytest.mark.parametrize(
    "sent,suggested",
    [
        ("HUMAN", "HU"),
        ("ORC", "OC"),
        ("UNDEAD", "UD"),
        ("NIGHTELF", "NE"),
        ("Random", "RANDOM"),
    ],
)
def test_a_race_that_misses_names_the_member_it_resembles(
    client: Client, auth_headers: dict[str, str], sent: str, suggested: str
) -> None:
    """The long names are the ones a caller is most likely to send."""
    resp = client.post(
        "/users",
        json={
            "name": "Bad",
            "battleTag": "Bad#9999",
            "discordTag": "bad",
            "discordId": "9999",
            "race": sent,
        },
        headers=auth_headers,
    )
    assert resp.status_code == 422
    assert f"Did you mean '{suggested}'?" in resp.json()["error"]


def test_a_race_that_resembles_nothing_lists_the_members(
    client: Client, auth_headers: dict[str, str]
) -> None:
    resp = client.post(
        "/users",
        json={
            "name": "Bad",
            "battleTag": "Bad#9999",
            "discordTag": "bad",
            "discordId": "9999",
            "race": "zzz",
        },
        headers=auth_headers,
    )
    assert resp.status_code == 422
    assert "Valid races are RANDOM, HU, OC, NE, UD." in resp.json()["error"]


@pytest.mark.parametrize("race", ["HUMAN", "human", "Random", "", "1"])
def test_a_player_created_with_an_invalid_race_is_refused(
    client: Client, auth_headers: dict[str, str], race: str
) -> None:
    resp = client.post(
        "/users",
        json={
            "name": "Bad",
            "battleTag": "Bad#9999",
            "discordTag": "bad",
            "discordId": "9999",
            "race": race,
        },
        headers=auth_headers,
    )
    assert resp.status_code == 422

    assert client.get("/users").status_code == 200
    assert client.get("/users").json() == []


@pytest.mark.parametrize("race", ["RANDOM", "HU", "OC", "NE", "UD"])
def test_a_player_created_with_a_valid_race_reads_back_as_that_string(
    client: Client, auth_headers: dict[str, str], race: str
) -> None:
    """The response carries the plain value, not "Race.HU"."""
    created = post(
        client,
        auth_headers,
        "/users",
        {
            "name": "Good",
            "battleTag": "Good#1",
            "discordTag": "good",
            "discordId": "1",
            "race": race,
        },
    )
    assert created["race"] == race
    assert get(client, f"/users/{created['id']}")["race"] == race
    assert get(client, "/users")[0]["race"] == race


def test_a_player_race_update_is_held_to_the_same_values(
    client: Client, auth_headers: dict[str, str], league: dict[str, Any]
) -> None:
    player_id = league["player_a_id"]
    resp = client.put(
        f"/users/{player_id}", json={"race": "HUMAN"}, headers=auth_headers
    )
    assert resp.status_code == 422

    put(client, auth_headers, f"/users/{player_id}", {"race": "NE"})
    assert get(client, f"/users/{player_id}")["race"] == "NE"


# Defects this branch records but does not fix.


@pytest.mark.xfail(
    strict=True,
    reason="update_series scores the request body instead of the stored row, "
    "so a missing second score reaches getScoreByMapScore as None and its "
    "bare Exception becomes a 500",
)
def test_a_result_with_one_score_missing_is_refused(
    client: Client, auth_headers: dict[str, str], league: dict[str, Any]
) -> None:
    """A half-entered result answers 500, not a 4xx."""
    resp = client.put(
        f"/series/{league['series_id']}",
        json={"player1_score": 1},
        headers=auth_headers,
    )
    assert resp.status_code < 500


def test_coaches_are_capped_at_three(
    client: Client, auth_headers: dict[str, str], league: dict[str, Any]
) -> None:
    path = f"/teams/{league['team_a_id']}/seasons/{league['season_id']}/coaches"
    resp = client.put(
        path, json={"coach_ids": [league["player_a_id"]]}, headers=auth_headers
    )
    assert resp.status_code == 200, resp.text

    resp = client.put(path, json={"coach_ids": [1, 2, 3, 4]}, headers=auth_headers)
    assert resp.status_code == 400
    assert "coaches" in resp.json()["error"]
