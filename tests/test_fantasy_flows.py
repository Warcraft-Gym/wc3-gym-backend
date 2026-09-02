"""The fantasy flows: the team scores, the bets and the team players.

The seeded league has one fantasy team with no drafted players. Its
captain P1 won the only played series 2-1 with a 10-point bet on
himself, and his race (HU) won its only series, so the race takes the
18 first-place points of week 1.
"""

from typing import Any

from httpx2 import Client


def get_json(client: Client, path: str) -> Any:  # noqa: ANN401  # a JSON body
    resp = client.get(path)
    assert resp.status_code == 200
    return resp.json()


def test_a_team_answers_its_totals_and_its_bet_results(
    client: Client, seeded: dict[str, Any]
) -> None:
    team = get_json(client, f"/fantasy/teams/{seeded['fantasy_team_id']}")
    assert team["player_points"] == 0
    assert team["bench_points"] == 0
    # The drafted team stands at 2, the sum of its series, not at null
    assert team["team_points"] == 2
    assert team["race_points"] == 18
    assert team["bet_points"] == 10
    assert team["total_points"] == 30

    bets = get_json(client, "/fantasy/bets")
    assert bets[0]["bet_result"] == 10


def test_a_drafted_player_scores_for_his_team(
    client: Client, seeded: dict[str, Any], auth_headers: dict[str, str]
) -> None:
    """A drafted player earns series points for played weeks and bench
    points for the weeks without a series."""
    team_id = seeded["fantasy_team_id"]
    p1 = seeded["player_ids"][0]
    resp = client.post(
        f"/fantasy/teams/{team_id}/players",
        json={"player_ids": [p1]},
        headers=auth_headers,
    )
    assert resp.status_code == 200

    team = get_json(client, f"/fantasy/teams/{team_id}")
    # Week 1: won 2-1 = 8 points. Weeks 2-4: no series = 3 * 5 bench points.
    assert team["player_points"] == 8
    assert team["bench_points"] == 15
    # The drafted team adds 2, the sum of its series, not at null
    assert team["total_points"] == 8 + 15 + 2 + 18 + 10


def test_breakdown_answers_the_race_value(
    client: Client, seeded: dict[str, Any]
) -> None:
    """The public page keys its race icons by the plain value ("HU"),
    so the breakdown must never answer the enum repr ("Race.HU")."""
    body = get_json(
        client,
        f"/fantasy/teams/{seeded['fantasy_team_id']}"
        f"/season/{seeded['season_id']}/breakdown",
    )
    race_breakdown = body["race_breakdown"]
    assert race_breakdown["race"] == "HU"
    assert race_breakdown["total_points"] == 18
    assert race_breakdown["all_race_points"] == {"HU": 18}


def test_bet_update_without_bet_points_keeps_them(
    client: Client, seeded: dict[str, Any], auth_headers: dict[str, str]
) -> None:
    bet = get_json(client, "/fantasy/bets")[0]
    other_player = seeded["player_ids"][2]
    resp = client.put(
        f"/fantasy/bets/{bet['id']}",
        json={"winner_id": other_player},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    updated = get_json(client, f"/fantasy/bets/{bet['id']}")
    assert updated["winner_id"] == other_player
    assert updated["bet_points"] == 10


def test_bet_update_carrying_bet_points_validates_them(
    client: Client, seeded: dict[str, Any], auth_headers: dict[str, str]
) -> None:
    bet = get_json(client, "/fantasy/bets")[0]
    for bad_value in (0, ""):
        resp = client.put(
            f"/fantasy/bets/{bet['id']}",
            json={"bet_points": bad_value},
            headers=auth_headers,
        )
        assert resp.status_code == 400
        assert "bet_points" in resp.json()["error"]


def test_add_and_remove_players(
    client: Client, seeded: dict[str, Any], auth_headers: dict[str, str]
) -> None:
    team_id = seeded["fantasy_team_id"]
    p1, p2 = seeded["player_ids"][:2]

    resp = client.post(
        f"/fantasy/teams/{team_id}/players",
        json={"player_ids": [p1, p2]},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert {p["id"] for p in resp.json()["drafted_players"]} == {p1, p2}

    resp = client.request(
        "DELETE",
        f"/fantasy/teams/{team_id}/players",
        json={"player_ids": [p2]},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert {p["id"] for p in resp.json()["drafted_players"]} == {p1}


def test_player_management_rejects_bad_input(
    client: Client, seeded: dict[str, Any], auth_headers: dict[str, str]
) -> None:
    team_id = seeded["fantasy_team_id"]
    p1 = seeded["player_ids"][0]

    # A body without player_ids is invalid, not a server error.
    resp = client.post(
        f"/fantasy/teams/{team_id}/players", json={}, headers=auth_headers
    )
    assert resp.status_code == 422
    assert "error" in resp.json()

    # Unknown ids answer 404: team, user, and a user not on the team.
    for method, path, body in [
        ("POST", "/fantasy/teams/9999/players", {"player_ids": [p1]}),
        ("POST", f"/fantasy/teams/{team_id}/players", {"player_ids": [9999]}),
        ("DELETE", f"/fantasy/teams/{team_id}/players", {"player_ids": [p1]}),
    ]:
        resp = client.request(method, path, json=body, headers=auth_headers)
        assert resp.status_code == 404, path
        assert "error" in resp.json()


def test_bets_list_pages_by_id_and_reports_the_total(
    client: Client, seeded: dict[str, Any]
) -> None:
    """limit and offset page the list by id; the header carries the total."""
    from app.core.db import Session
    from tests.seed import add_bets

    with Session() as session:
        add_bets(session, seeded, 4)
        session.commit()

    everything = client.get("/fantasy/bets")
    assert everything.headers["X-Total-Count"] == "5"
    ids = [bet["id"] for bet in everything.json()]
    assert len(ids) == 5

    paged = []
    for offset in (0, 2, 4):
        resp = client.get(f"/fantasy/bets?limit=2&offset={offset}")
        assert resp.status_code == 200
        assert resp.headers["X-Total-Count"] == "5"
        paged += [bet["id"] for bet in resp.json()]
    assert paged == sorted(ids)


def test_bets_list_rejects_a_bad_page(client: Client, seeded: dict[str, Any]) -> None:
    """limit under 1 and offset under 0 answer 422."""
    assert client.get("/fantasy/bets?limit=0").status_code == 422
    assert client.get("/fantasy/bets?offset=-1").status_code == 422


def test_bets_search_pages_by_id_and_counts_the_filtered_set(
    client: Client, seeded: dict[str, Any]
) -> None:
    """limit and offset page the search; the total counts the filter matches."""
    from app.core.db import Session
    from tests.seed import add_bets

    with Session() as session:
        add_bets(session, seeded, 4)
        session.commit()

    query = f"user_id == {seeded['player_ids'][1]}"
    everything = client.post(f"/fantasy/bets/search?query={query}")
    assert everything.headers["X-Total-Count"] == "4"
    ids = [bet["id"] for bet in everything.json()]
    assert len(ids) == 4

    paged = []
    for offset in (0, 3):
        resp = client.post(
            f"/fantasy/bets/search?query={query}&limit=3&offset={offset}"
        )
        assert resp.status_code == 200
        assert resp.headers["X-Total-Count"] == "4"
        paged += [bet["id"] for bet in resp.json()]
    assert paged == sorted(ids)


# Five ascending boundaries cut a six-tier season
CUTS = [900, 1100, 1300, 1500, 1700]


def _tier_of(client: Client, season_id: int, user_id: int) -> int | None:
    """The tier the season's signup row carries for one player."""
    rows = get_json(client, f"/seasons/{season_id}/signups")
    return next(row["fantasy_tier"] for row in rows if row["id"] == user_id)


def test_tier_allocation_replaces_the_whole_map_at_once(
    client: Client, seeded: dict[str, Any], auth_headers: dict[str, str]
) -> None:
    """One PUT sets every listed tier on the season's signup rows and clears the rest."""
    season = seeded["season_id"]
    p1, p2 = seeded["player_ids"][:2]
    client.post(
        f"/seasons/{season}/signups", json={"user_ids": [p1, p2]}, headers=auth_headers
    )

    resp = client.put(
        f"/fantasy/tiers?season_id={season}",
        json={"cuts": CUTS, "tiers": {str(p1): 1, str(p2): 3}},
        headers=auth_headers,
    )
    assert resp.status_code == 204
    assert _tier_of(client, season, p1) == 1
    assert _tier_of(client, season, p2) == 3

    resp = client.put(
        f"/fantasy/tiers?season_id={season}",
        json={"cuts": CUTS, "tiers": {str(p2): 2}},
        headers=auth_headers,
    )
    assert resp.status_code == 204
    assert _tier_of(client, season, p1) is None
    assert _tier_of(client, season, p2) == 2

    assert (
        client.put(
            f"/fantasy/tiers?season_id={season}",
            json={"cuts": CUTS, "tiers": {str(p1): 0}},
            headers=auth_headers,
        ).status_code
        == 422
    )
    assert client.put(
        f"/fantasy/tiers?season_id={season}", json={"cuts": CUTS, "tiers": {str(p1): 1}}
    ).status_code in (401, 403)


def test_a_tier_allocation_names_its_season(
    client: Client, seeded: dict[str, Any], auth_headers: dict[str, str]
) -> None:
    """The tier lives on the signup row, so the season is required and an
    allocation leaves the user answer's tier empty."""
    season = seeded["season_id"]
    p1 = seeded["player_ids"][0]
    resp = client.put(
        "/fantasy/tiers",
        json={"cuts": CUTS, "tiers": {str(p1): 1}},
        headers=auth_headers,
    )
    assert resp.status_code == 422

    client.post(
        f"/seasons/{season}/signups", json={"user_ids": [p1]}, headers=auth_headers
    )
    resp = client.put(
        f"/fantasy/tiers?season_id={season}",
        json={"cuts": CUTS, "tiers": {str(p1): 1}},
        headers=auth_headers,
    )
    assert resp.status_code == 204
    assert _tier_of(client, season, p1) == 1
    assert get_json(client, f"/users/{p1}")["fantasy_tier"] is None


def test_the_cuts_make_the_tiers(
    client: Client, seeded: dict[str, Any], auth_headers: dict[str, str]
) -> None:
    """The tier count is one more than the cuts, so a tier above it is refused, and
    the cuts must be one to five strictly ascending MMRs."""
    season = seeded["season_id"]
    p1 = seeded["player_ids"][0]
    client.post(
        f"/seasons/{season}/signups", json={"user_ids": [p1]}, headers=auth_headers
    )
    before = get_json(client, f"/seasons/{season}")
    assert (before["fantasy_tiers"], before["fantasy_tier_cuts"]) == (0, [])

    def put(cuts: list[int], tier: int) -> int:
        return client.put(
            f"/fantasy/tiers?season_id={season}",
            json={"cuts": cuts, "tiers": {str(p1): tier}},
            headers=auth_headers,
        ).status_code

    assert put(CUTS[:3], 5) == 400
    assert _tier_of(client, season, p1) is None
    for cuts in ([], CUTS + [1900], [900, 900, 1100], [1300, 1100, 900]):
        assert put(cuts, 1) == 400, cuts

    assert put(CUTS[:3], 4) == 204
    assert _tier_of(client, season, p1) == 4
    after = get_json(client, f"/seasons/{season}")
    assert (after["fantasy_tiers"], after["fantasy_tier_cuts"]) == (4, CUTS[:3])
    # A one-point tier is legal: exactly 1100 is its own tier
    assert put([900, 1100, 1101], 4) == 204


def test_tiers_are_refused_for_players_not_signed_up(
    client: Client, seeded: dict[str, Any], auth_headers: dict[str, str]
) -> None:
    """The tier lives on the signup row, so a player without one is a bad request."""
    p1 = seeded["player_ids"][0]
    season = client.post(
        "/seasons",
        json={"name": "No signups", "number_weeks": 1, "series_per_week": 1},
        headers=auth_headers,
    ).json()["id"]
    resp = client.put(
        f"/fantasy/tiers?season_id={season}",
        json={"cuts": CUTS, "tiers": {str(p1): 1}},
        headers=auth_headers,
    )
    assert resp.status_code == 400
    assert "not signed up" in str(resp.json()["error"])


def test_each_season_keeps_its_own_tiers(
    client: Client, seeded: dict[str, Any], auth_headers: dict[str, str]
) -> None:
    """Allocating one season leaves another season's tiers alone."""
    first = seeded["season_id"]
    p1 = seeded["player_ids"][0]
    second = client.post(
        "/seasons",
        json={"name": "Second", "number_weeks": 1, "series_per_week": 1},
        headers=auth_headers,
    ).json()["id"]
    for season in (first, second):
        client.post(
            f"/seasons/{season}/signups", json={"user_ids": [p1]}, headers=auth_headers
        )

    client.put(
        f"/fantasy/tiers?season_id={first}",
        json={"cuts": CUTS, "tiers": {str(p1): 1}},
        headers=auth_headers,
    )
    client.put(
        f"/fantasy/tiers?season_id={second}",
        json={"cuts": CUTS, "tiers": {str(p1): 5}},
        headers=auth_headers,
    )

    assert _tier_of(client, first, p1) == 1
    assert _tier_of(client, second, p1) == 5
