"""The fantasy write flows: score calculation, bets, team players.

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


def test_calculate_writes_totals_and_bet_results(
    client: Client, seeded: dict[str, Any], auth_headers: dict[str, str]
) -> None:
    resp = client.post(
        f"/fantasy/season/{seeded['season_id']}/calculate/", headers=auth_headers
    )
    assert resp.status_code == 204

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


def test_calculate_scores_drafted_players(
    client: Client, seeded: dict[str, Any], auth_headers: dict[str, str]
) -> None:
    """A drafted player earns series points for played weeks and bench
    points for the weeks without a series."""
    team_id = seeded["fantasy_team_id"]
    p1 = seeded["player_ids"][0]
    resp = client.post(
        f"/fantasy/teams/addPlayers/{team_id}",
        json={"player_ids": [p1]},
        headers=auth_headers,
    )
    assert resp.status_code == 200

    resp = client.post(
        f"/fantasy/season/{seeded['season_id']}/calculate/", headers=auth_headers
    )
    assert resp.status_code == 204

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
        f"/fantasy/teams/addPlayers/{team_id}",
        json={"player_ids": [p1, p2]},
        headers=auth_headers,
    )
    assert resp.status_code == 200
    assert {p["id"] for p in resp.json()["drafted_players"]} == {p1, p2}

    resp = client.post(
        f"/fantasy/teams/removePlayers/{team_id}",
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
        f"/fantasy/teams/addPlayers/{team_id}", json={}, headers=auth_headers
    )
    assert resp.status_code == 422
    assert "error" in resp.json()

    # Unknown ids answer 404: team, user, and a user not on the team.
    for path, body in [
        ("/fantasy/teams/addPlayers/9999", {"player_ids": [p1]}),
        (f"/fantasy/teams/addPlayers/{team_id}", {"player_ids": [9999]}),
        (f"/fantasy/teams/removePlayers/{team_id}", {"player_ids": [p1]}),
    ]:
        resp = client.post(path, json=body, headers=auth_headers)
        assert resp.status_code == 404, path
        assert "error" in resp.json()


def test_calculate_twice_is_stable(
    client: Client, seeded: dict[str, Any], auth_headers: dict[str, str]
) -> None:
    path = f"/fantasy/season/{seeded['season_id']}/calculate/"
    assert client.post(path, headers=auth_headers).status_code == 204
    first = get_json(client, f"/fantasy/teams/{seeded['fantasy_team_id']}")
    assert client.post(path, headers=auth_headers).status_code == 204
    second = get_json(client, f"/fantasy/teams/{seeded['fantasy_team_id']}")
    assert first == second


def test_bets_list_pages_by_id_and_reports_the_total(
    client: Client, seeded: dict[str, Any]
) -> None:
    """limit and offset page the list by id; the header carries the total."""
    from app.core.db import Session
    from app.models.fantasy_bet import FantasyBet

    with Session() as session:
        for _ in range(4):
            session.add(
                FantasyBet(
                    season_id=seeded["season_id"],
                    series_id=seeded["series_played_id"],
                    user_id=seeded["player_ids"][1],
                    winner_id=seeded["player_ids"][0],
                    bet_points=10,
                )
            )
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
    from app.models.fantasy_bet import FantasyBet

    with Session() as session:
        for _ in range(4):
            session.add(
                FantasyBet(
                    season_id=seeded["season_id"],
                    series_id=seeded["series_played_id"],
                    user_id=seeded["player_ids"][1],
                    winner_id=seeded["player_ids"][0],
                    bet_points=10,
                )
            )
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
