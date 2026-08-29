"""The JSON the public consumers read, pinned against seeded data.

The offline leaderboard generation consumes this JSON, so field names and
value formats are a public contract. These tests assert the fields those
consumers depend on, not every field, so an added field passes and a
renamed or retyped one fails.
"""

from typing import Any

from httpx2 import Client

from app.core.db import Session
from app.models.enums import Race
from app.models.relationships import DBUserSeasonSignup
from app.models.w3c_stats import W3CStats

BET_KEYS = {
    "id",
    "season_id",
    "series_id",
    "user_id",
    "winner_id",
    "bet_points",
    "bet_result",
    "season",
    "series",
    "user",
    "winner",
}


def get_json(client: Client, path: str) -> Any:  # noqa: ANN401  # a JSON body
    resp = client.get(path)
    assert resp.status_code == 200
    return resp.json()


def test_users_list(client: Client, seeded: dict[str, Any]) -> None:
    users = get_json(client, "/users")
    assert len(users) == 4
    by_tag = {u["battleTag"]: u for u in users}
    p1 = by_tag["P1#1111"]
    assert p1["name"] == "P1"
    assert p1["race"] == "HU"
    assert p1["mmr"] == 1500
    assert p1["country"] == "DE"
    # The list row carries no gnl_stats; the player page reads them by id.
    assert "gnl_stats" not in p1


def test_user_by_id_carries_the_season_record(
    client: Client, seeded: dict[str, Any]
) -> None:
    """gnl_stats names its team and its season by id."""
    p1 = get_json(client, f"/users/{seeded['player_ids'][0]}")
    assert len(p1["gnl_stats"]) == 1
    stats = p1["gnl_stats"][0]
    assert stats["season_id"] == seeded["season_id"]
    assert stats["team_id"] == seeded["team_a_id"]
    assert set(stats) == {
        "user_id",
        "team_id",
        "season_id",
        "games",
        "wins",
        "losses",
        "matchup_history",
    }


def test_season_signups_answer_list_rows(
    client: Client, seeded: dict[str, Any]
) -> None:
    """The signup row carries the scalars and the w3c stats, no gnl_stats."""
    with Session() as session:
        session.add(
            DBUserSeasonSignup(
                user_id=seeded["player_ids"][0], season_id=seeded["season_id"]
            )
        )
        session.commit()

    rows = get_json(client, f"/seasons/{seeded['season_id']}/signups")
    assert len(rows) == 1
    assert rows[0]["battleTag"] == "P1#1111"
    assert rows[0]["w3c_stats"] == []
    assert "gnl_stats" not in rows[0]


def test_match_by_id_carries_the_season_length(
    client: Client, seeded: dict[str, Any]
) -> None:
    """The match page reads number_weeks here, not from /seasons/{id}."""
    match = get_json(client, f"/matches/{seeded['match_id']}")
    assert match["season"]["id"] == seeded["season_id"]
    assert match["season"]["number_weeks"] == 4
    assert match["season"]["series_per_week"] == 2


def test_seasons_list(client: Client, seeded: dict[str, Any]) -> None:
    seasons = get_json(client, "/seasons")
    assert len(seasons) == 1
    season = seasons[0]
    assert season["name"] == "Season 1"
    assert season["number_weeks"] == 4
    assert season["series_per_week"] == 2
    # Dates serialize as ISO strings.
    assert season["start_date"] == "2026-01-05"
    assert season["end_date"] == "2026-02-27"
    assert [m["shortname"] for m in season["maps"]] == ["CH"]


def test_teams_basic(client: Client, seeded: dict[str, Any]) -> None:
    teams = get_json(client, "/teams/basic")
    assert {t["name"] for t in teams} == {"Alpha", "Beta"}
    alpha = next(t for t in teams if t["name"] == "Alpha")
    assert alpha["long_name"] == "Team Alpha"


def test_series_for_season(client: Client, seeded: dict[str, Any]) -> None:
    ids = seeded
    series = get_json(client, f"/series/season/{ids['season_id']}")
    assert len(series) == 2
    played = next(s for s in series if s["id"] == ids["series_played_id"])
    assert played["player1_score"] == 2
    assert played["player2_score"] == 1
    assert played["player1_points"] == 2
    assert played["player2_points"] == 1
    assert played["date_time"] == "2026-01-07T19:00:00Z"
    assert played["match"]["playday"] == 1
    open_series = next(s for s in series if s["id"] == ids["series_open_id"])
    assert open_series["player1_score"] is None
    assert open_series["player1_points"] is None


def test_career_stats(client: Client, seeded: dict[str, Any]) -> None:
    # Two stored rows, and P3 who played a series and holds none
    stats = get_json(client, "/stats/career")
    assert len(stats) == 3
    p1 = next(s for s in stats if s["player_name"] == "P1")
    assert p1["series_won"] == 1
    assert p1["games_won"] == 2
    assert p1["games_lost"] == 1
    assert p1["user"]["battleTag"] == "P1#1111"


def test_settings(client: Client, seeded: dict[str, Any]) -> None:
    body = get_json(client, "/config/settings")
    by_key = {s["key"]: s["value"] for s in body["settings"]}
    assert by_key["score_system"] == "standard"


def test_fantasy_bets(client: Client, seeded: dict[str, Any]) -> None:
    bets = get_json(client, "/fantasy/bets")
    assert len(bets) == 1
    bet = bets[0]
    assert bet["bet_points"] == 10
    # P1 called himself and won the series 2-1, so the bet pays its stake
    assert bet["bet_result"] == 10
    assert bet["series"]["id"] == seeded["series_played_id"]


def test_fantasy_bets_list_keeps_every_key_with_empty_collections(
    client: Client, seeded: dict[str, Any]
) -> None:
    """The list answers the whole bet shape and empty nested collections."""
    with Session() as session:
        for user_id in seeded["player_ids"]:
            session.add(
                W3CStats(user_id=user_id, wc3_season=20, race=Race.HU, mmr=1500)
            )
            session.add(
                DBUserSeasonSignup(user_id=user_id, season_id=seeded["season_id"])
            )
        session.commit()

    bet = get_json(client, "/fantasy/bets")[0]
    assert set(bet) == BET_KEYS

    # The admin bets table reads these fields.
    assert bet["bet_points"] == 10
    assert bet["winner_id"] == seeded["player_ids"][0]
    assert bet["user"]["name"] == "P1"
    assert bet["series"]["player1"]["name"] == "P1"
    assert bet["series"]["player2"]["name"] == "P3"
    assert bet["series"]["player1_id"] == seeded["player_ids"][0]
    assert bet["series"]["player2_id"] == seeded["player_ids"][2]
    assert bet["series"]["player1_score"] == 2
    assert bet["series"]["player2_score"] == 1

    # The scalars of the embedded models stay.
    assert bet["season"]["name"] == "Season 1"
    assert bet["season"]["number_weeks"] == 4
    assert bet["season"]["start_date"] == "2026-01-05"
    assert bet["series"]["match"]["playday"] == 1
    assert bet["series"]["match"]["team1"]["name"] == "Alpha"

    # The collections inside the embedded models are empty.
    assert bet["season"]["maps"] == []
    assert bet["season"]["user_signup"] == []
    for user in (
        bet["user"],
        bet["winner"],
        bet["series"]["player1"],
        bet["series"]["player2"],
    ):
        assert user["w3c_stats"] == []
        assert user["gnl_stats"] == []
        assert user["signup_seasons"] == []


def test_fantasy_bet_by_id_keeps_the_full_graph(
    client: Client, seeded: dict[str, Any]
) -> None:
    """The single-bet route still answers the nested collections."""
    with Session() as session:
        session.add(
            W3CStats(
                user_id=seeded["player_ids"][0], wc3_season=20, race=Race.HU, mmr=1500
            )
        )
        session.commit()

    bet_id = get_json(client, "/fantasy/bets")[0]["id"]
    bet = get_json(client, f"/fantasy/bets/{bet_id}")
    assert set(bet) == BET_KEYS
    assert len(bet["user"]["w3c_stats"]) == 1
    assert len(bet["user"]["gnl_stats"]) == 1
    assert [m["shortname"] for m in bet["season"]["maps"]] == ["CH"]


def test_fantasy_teams(client: Client, seeded: dict[str, Any]) -> None:
    teams = get_json(client, "/fantasy/teams")
    assert len(teams) == 1
    team = teams[0]
    assert team["name"] == "The Optimists"
    assert team["captain"]["battleTag"] == "P1#1111"
    assert team["drafted_race"] == "HU"


def test_empty_database_returns_empty_lists(client: Client) -> None:
    for path in ["/users", "/seasons", "/maps", "/stats/career"]:
        assert get_json(client, path) == []


def test_series_season_list_keeps_every_key_with_empty_collections(
    client: Client, seeded: dict[str, Any]
) -> None:
    """The season series list answers reduced players; the scalars stay."""
    with Session() as session:
        for user_id in seeded["player_ids"]:
            session.add(
                W3CStats(user_id=user_id, wc3_season=20, race=Race.HU, mmr=1500)
            )
        session.commit()

    series = get_json(client, f"/series/season/{seeded['season_id']}")[0]
    assert series["player1"]["name"]
    assert series["player1"]["race"]
    assert series["match"]["team1"]["name"]
    for player in (series["player1"], series["player2"]):
        assert player["w3c_stats"] == []
        assert player["gnl_stats"] == []
        assert player["signup_seasons"] == []


def test_series_by_id_keeps_the_full_graph(
    client: Client, seeded: dict[str, Any]
) -> None:
    """The single-series route still answers the nested collections."""
    with Session() as session:
        session.add(
            W3CStats(
                user_id=seeded["player_ids"][0], wc3_season=20, race=Race.HU, mmr=1500
            )
        )
        session.commit()

    series = get_json(client, f"/series/{seeded['series_played_id']}")
    assert len(series["player1"]["w3c_stats"]) == 1


def test_fantasy_teams_list_keeps_every_key_with_empty_collections(
    client: Client, seeded: dict[str, Any]
) -> None:
    """The list keeps the nested objects; their sub-collections are empty."""
    team = get_json(client, "/fantasy/teams")[0]
    assert team["captain"]["name"]
    assert team["season"]["name"]
    assert team["drafted_team"]["name"]
    assert team["captain"]["signup_seasons"] == []
    assert team["season"]["maps"] == []
    assert team["drafted_team"]["player_by_season"] == {}
    assert team["drafted_team"]["seasons_info"] == []


def test_teams_list_keeps_scalars_and_standings(
    client: Client, seeded: dict[str, Any]
) -> None:
    """The plain teams list answers scalars and standings, no rosters."""
    team = get_json(client, "/teams")[0]
    assert team["name"]
    assert "long_name" in team
    assert isinstance(team["seasons_info"], list) and team["seasons_info"]
    assert "final_score" in team["seasons_info"][0]
    assert team["player_by_season"] == {}
    assert team["coaches_by_season"] == {}
