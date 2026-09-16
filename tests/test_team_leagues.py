"""Teams belong to leagues; their rosters belong to events of that league."""

from typing import Any

from httpx2 import Client

from app.core.db import Session
from app.models.base import ident
from app.models.league import League
from app.models.team import Team


def test_the_league_team_routes_scope_identity_and_the_event_routes_scope_rosters(
    client: Client, seeded: dict[str, Any]
) -> None:
    league_id = seeded["league_id"]
    team_id = seeded["team_a_id"]
    event_id = seeded["season_id"]

    league_teams = client.get(f"/leagues/{league_id}/teams").json()
    assert [team["id"] for team in league_teams] == [team_id, seeded["team_b_id"]]
    assert all(team["league_id"] == league_id for team in league_teams)

    event_team = client.get(f"/events/{event_id}/teams/{team_id}").json()
    assert [
        player["id"] for player in event_team["player_by_season"][str(event_id)]
    ] == seeded["player_ids"][:2]


def test_a_team_cannot_join_an_event_of_another_league(
    client: Client, seeded: dict[str, Any], auth_headers: dict[str, str]
) -> None:
    with Session.begin() as session:
        league = League(name="Another League")
        session.add(league)
        session.flush()
        team = Team(name="Visitors", league_id=ident(league))
        session.add(team)
        session.flush()
        league_id = ident(league)
        team_id = ident(team)

    response = client.post(
        f"/events/{seeded['season_id']}/teams",
        json={"team_ids": [team_id]},
        headers=auth_headers,
    )
    assert response.status_code == 400
    assert "not event league" in response.json()["error"]

    response = client.put(
        f"/events/{seeded['season_id']}",
        json={"league_id": league_id},
        headers=auth_headers,
    )
    assert response.status_code == 400
    assert "Remove the event's teams" in response.json()["error"]


def test_the_unscoped_and_season_named_team_routes_are_deprecated(
    client: Client,
) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    old_paths = [
        "/teams",
        "/teams/basic",
        "/teams/search",
        "/teams/{team_id}",
        "/teams/{team_id}/image",
        "/teams/season/{event_id}",
        "/teams/season/{event_id}/basic",
        "/teams/{team_id}/seasons/{event_id}",
        "/teams/{team_id}/seasons/{event_id}/availability",
        "/teams/{team_id}/seasons/{event_id}/captains",
        "/teams/{team_id}/seasons/{event_id}/players",
        "/teams/{team_id}/seasons/{event_id}/w3c-sync",
        "/seasons/{event_id}/teams",
        "/series/season/{event_id}",
        "/series/season/{event_id}/search",
        "/series/season/{event_id}/playday/{playday}/search",
        "/fantasy/tiers",
        "/fantasy/teams/{team_id}/season/{event_id}/breakdown",
    ]
    assert all(
        operation.get("deprecated") is True
        for path in old_paths
        for operation in paths[path].values()
    )
