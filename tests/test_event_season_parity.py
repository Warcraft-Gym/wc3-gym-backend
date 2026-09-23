"""The event API that serves a GNL season."""

from typing import Any

from httpx2 import Client

from app.core.db import Session
from app.models.base import ident
from app.models.enums import EntrantKind, LeagueKind
from app.models.league import League
from app.models.map import Map


def create_gnl_event(client: Client, headers: dict[str, str]) -> dict[str, Any]:
    """Create the GNL league, a map and one complete event through /events."""
    with Session.begin() as session:
        league = League(
            name="Gym Newbie League",
            short_name="GNL",
            kind=LeagueKind.gnl,
            entrant_kind=EntrantKind.drafted_teams,
        )
        game_map = Map(name="Concealed Hill", shortname="CH")
        session.add_all([league, game_map])
        session.flush()
        league_id, map_id = ident(league), ident(game_map)

    response = client.post(
        "/events",
        json={
            "league_id": league_id,
            "name": "Season 19",
            "round_count": 3,
            "map_ids": [map_id],
            "series_per_round": 5,
            "map_rules": "fixed,loser,loser",
            "score_system": "helpstone",
            "fantasy_grind": True,
        },
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_events_create_a_complete_gnl_run(
    client: Client, auth_headers: dict[str, str]
) -> None:
    event = create_gnl_event(client, auth_headers)

    assert event["kind"] == "gnl"
    assert event["league_short_name"] == "GNL"
    assert event["entrant_kind"] == "drafted_teams"
    assert event["round_count"] == 3
    assert [row["playday"] for row in event["rounds"]] == [1, 2, 3]
    assert [game_map["shortname"] for game_map in event["maps"]] == ["CH"]
    assert event["score_system"] == "helpstone"
    assert event["fantasy_grind"] is True
    assert [(stage["position"], stage["format"]) for stage in event["stages"]] == [
        (1, "gnl")
    ]
    assert client.get(f"/events/{event['id']}/achievements").json()


def test_event_reads_carry_the_useful_season_fields(
    client: Client, auth_headers: dict[str, str]
) -> None:
    created = create_gnl_event(client, auth_headers)
    event = client.get(f"/events/{created['id']}").json()

    fields = {
        "round_count",
        "pick_ban",
        "discordRole",
        "score_system",
        "fantasy_grind",
        "fantasy_tiers",
        "fantasy_tier_cuts",
        "fantasy_tiers_applied_at",
        "unscored_series",
        "maps",
        "rounds",
    }
    listed = client.get(f"/events?league_id={created['league_id']}").json()
    assert len(listed) == 1
    assert {key: listed[0][key] for key in fields} == {
        key: event[key] for key in fields
    }


def test_the_season_routes_live_under_events_only(client: Client) -> None:
    paths = client.get("/openapi.json").json()["paths"]
    assert not [path for path in paths if path.startswith("/seasons")]

    event_routes = {
        ("post", "/events"),
        ("post", "/events/search"),
        ("get", "/events/{event_id}"),
        ("put", "/events/{event_id}"),
        ("delete", "/events/{event_id}"),
        ("post", "/events/{event_id}/teams"),
        ("get", "/events/{event_id}/teams"),
        ("delete", "/events/{event_id}/teams"),
        ("get", "/events/{event_id}/teams/basic"),
        ("get", "/events/{event_id}/teams/{team_id}"),
        ("get", "/events/{event_id}/series"),
        ("post", "/events/{event_id}/series/search"),
        ("get", "/events/{event_id}/fantasy/teams"),
        ("post", "/events/{event_id}/maps"),
        ("delete", "/events/{event_id}/maps"),
        ("get", "/events/{event_id}/maps/ladder-import"),
        ("post", "/events/{event_id}/maps/ladder-import"),
        ("put", "/events/{event_id}/maps/order"),
        ("put", "/events/{event_id}/rounds"),
        ("post", "/events/{event_id}/signups"),
        ("delete", "/events/{event_id}/signups"),
        ("put", "/events/{event_id}/signups/{user_id}"),
        ("get", "/events/{event_id}/signups"),
        ("post", "/events/{event_id}/ladder-sync"),
        ("get", "/events/{event_id}/achievements"),
        ("put", "/events/{event_id}/achievements"),
        ("get", "/events/{event_id}/ladder"),
        ("get", "/events/{event_id}/ladder/players"),
    }
    for method, path in event_routes:
        assert path in paths
        methods = paths[path]
        assert method in methods
        assert methods[method].get("deprecated") is not True

    assert client.get("/openapi.json").json()["info"]["version"] == "1.1.0"
