"""The JSON the public consumers read, pinned against seeded data.

The offline leaderboard generation consumes this JSON, so field names and
value formats are a public contract. These tests assert the fields those
consumers depend on, not every field, so an added field passes and a
renamed or retyped one fails.
"""


def get_json(client, path):
    resp = client.get(path)
    assert resp.status_code == 200
    return resp.json()


def test_users_list(client, seeded):
    users = get_json(client, "/users")
    assert len(users) == 4
    by_tag = {u["battleTag"]: u for u in users}
    p1 = by_tag["P1#1111"]
    assert p1["name"] == "P1"
    assert p1["race"] == "HU"
    assert p1["mmr"] == 1500
    assert p1["country"] == "DE"
    # gnl_stats carries the player's team and season memberships.
    assert len(p1["gnl_stats"]) == 1
    assert p1["gnl_stats"][0]["season"]["name"] == "Season 1"
    assert p1["gnl_stats"][0]["team"]["name"] == "Alpha"


def test_seasons_list(client, seeded):
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


def test_teams_basic(client, seeded):
    teams = get_json(client, "/teams/basic")
    assert {t["name"] for t in teams} == {"Alpha", "Beta"}
    alpha = next(t for t in teams if t["name"] == "Alpha")
    assert alpha["long_name"] == "Team Alpha"


def test_series_for_season(client, seeded):
    ids = seeded
    series = get_json(client, f"/series/season/{ids['season_id']}")
    assert len(series) == 2
    played = next(s for s in series if s["id"] == ids["series_played_id"])
    assert played["player1_score"] == 2
    assert played["player2_score"] == 1
    assert played["player1_points"] == 2
    assert played["player2_points"] == 1
    assert played["date_time"] == "2026-01-07T19:00:00"
    assert played["match"]["playday"] == 1
    open_series = next(s for s in series if s["id"] == ids["series_open_id"])
    assert open_series["player1_score"] is None
    assert open_series["player1_points"] is None


def test_career_stats(client, seeded):
    stats = get_json(client, "/stats/career")
    assert len(stats) == 2
    p1 = next(s for s in stats if s["player_name"] == "P1")
    assert p1["series_won"] == 1
    assert p1["games_won"] == 2
    assert p1["games_lost"] == 1
    assert p1["user"]["battleTag"] == "P1#1111"


def test_settings(client, seeded):
    body = get_json(client, "/config/settings")
    by_key = {s["key"]: s["value"] for s in body["settings"]}
    assert by_key["score_system"] == "standard"


def test_fantasy_bets(client, seeded):
    bets = get_json(client, "/fantasy/bets")
    assert len(bets) == 1
    bet = bets[0]
    assert bet["bet_points"] == 10
    assert bet["bet_result"] is None
    assert bet["series"]["id"] == seeded["series_played_id"]


def test_fantasy_teams(client, seeded):
    teams = get_json(client, "/fantasy/teams")
    assert len(teams) == 1
    team = teams[0]
    assert team["name"] == "The Optimists"
    assert team["captain"]["battleTag"] == "P1#1111"
    assert team["drafted_race"] == "HU"


def test_empty_database_returns_empty_lists(client):
    for path in ["/users", "/seasons", "/maps", "/stats/career"]:
        assert get_json(client, path) == []
