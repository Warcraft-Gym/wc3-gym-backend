"""No route that carries a race writes the enum repr, and a bet row carries
its two sides.

The public fantasy page prints race_breakdown.race straight into the markup and
passes it to RaceIcon, where it is matched against the ids in the frontend's
races.js. A value carrying the enum repr, "Race.HU", printed as that text and
matched nothing, so the icon rendered as blank.

test_fantasy_flows pins the values of that breakdown; this file pins that no
route anywhere writes the repr.
"""

from typing import Any

from httpx2 import Client


def breakdown(client: Client, seeded: dict[str, Any]) -> dict[str, Any]:
    resp = client.get(
        f"/fantasy/teams/{seeded['fantasy_team_id']}/season/{seeded['season_id']}/breakdown"
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_no_route_that_carries_a_race_writes_the_repr(
    client: Client, seeded: dict[str, Any]
) -> None:
    """The response models render the value, so only a body built by hand
    can carry the repr. These are the routes that carry a race."""
    team_id = seeded["fantasy_team_id"]
    season_id = seeded["season_id"]
    paths = [
        "/users",
        f"/users/{seeded['player_ids'][0]}",
        f"/teams/{seeded['team_a_id']}/seasons/{season_id}",
        f"/series/{seeded['series_played_id']}",
        "/fantasy/teams",
        f"/fantasy/teams/{team_id}",
        f"/fantasy/teams/{team_id}/season/{season_id}/breakdown",
    ]
    for path in paths:
        resp = client.get(path)
        assert resp.status_code == 200, (path, resp.status_code)
        assert "Race." not in resp.text, path


def test_a_bet_row_carries_the_two_players_and_the_score(
    client: Client, seeded: dict[str, Any]
) -> None:
    """The bet tab draws both sides and the series score, so the row carries
    them as fields rather than the page splitting `series` on " vs "."""
    row = breakdown(client, seeded)["bet_breakdown"][0]

    assert row["player1"] == "P1"
    assert row["player2"] == "P3"
    assert row["series"] == "P1 vs P3"
    assert row["score"] == "2-1"
    assert row["actual_winner"] == "P1"
