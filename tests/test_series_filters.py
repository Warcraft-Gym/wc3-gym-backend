"""GET /events/{event_id}/series filters by player, team, match and fantasy flag.

Each one narrows the season's series list, and given together they AND.
The seeded season holds one match with two series: series_played
(P1 vs P3) and series_open (P2 vs P4).
"""

from typing import Any

from httpx2 import Client

from app.models.series import SeriesUpdate
from app.services.series import SeriesService


def series_rows(
    client: Client, season_id: int, **params: int | bool
) -> list[dict[str, Any]]:
    resp = client.get(f"/events/{season_id}/series", params=params)
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_no_filter_answers_every_series_of_the_season(
    client: Client, seeded: dict[str, Any]
) -> None:
    rows = series_rows(client, seeded["season_id"])
    assert {row["id"] for row in rows} == {
        seeded["series_played_id"],
        seeded["series_open_id"],
    }


def test_player_id_keeps_only_that_players_series(
    client: Client, seeded: dict[str, Any]
) -> None:
    third_player = seeded["player_ids"][2]  # P3, plays in series_played only
    unfiltered = series_rows(client, seeded["season_id"])
    rows = series_rows(client, seeded["season_id"], player_id=third_player)
    assert [row["id"] for row in rows] == [seeded["series_played_id"]]
    assert set(rows[0]) == set(unfiltered[0])


def test_team_id_keeps_series_of_the_teams_matches(
    client: Client, seeded: dict[str, Any]
) -> None:
    rows = series_rows(client, seeded["season_id"], team_id=seeded["team_b_id"])
    assert {row["id"] for row in rows} == {
        seeded["series_played_id"],
        seeded["series_open_id"],
    }


def test_match_id_keeps_only_that_matchs_series(
    client: Client, seeded: dict[str, Any]
) -> None:
    rows = series_rows(client, seeded["season_id"], match_id=seeded["match_id"])
    assert {row["id"] for row in rows} == {
        seeded["series_played_id"],
        seeded["series_open_id"],
    }


def test_unmatched_and_combined_filters(client: Client, seeded: dict[str, Any]) -> None:
    """A filter matching nothing answers []; two filters AND together."""
    unknown = 999999
    assert series_rows(client, seeded["season_id"], player_id=unknown) == []
    assert series_rows(client, seeded["season_id"], team_id=unknown) == []

    first_player = seeded["player_ids"][0]  # P1, plays in series_played only
    rows = series_rows(
        client,
        seeded["season_id"],
        player_id=first_player,
        team_id=seeded["team_b_id"],
    )
    assert [row["id"] for row in rows] == [seeded["series_played_id"]]


def test_is_fantasy_match_splits_fantasy_from_the_rest(
    client: Client, seeded: dict[str, Any]
) -> None:
    """series_open keeps a null flag, which counts as not fantasy."""
    SeriesService().update(
        seeded["series_played_id"], SeriesUpdate(is_fantasy_match=True)
    )
    fantasy = series_rows(client, seeded["season_id"], is_fantasy_match=True)
    rest = series_rows(client, seeded["season_id"], is_fantasy_match=False)
    assert [row["id"] for row in fantasy] == [seeded["series_played_id"]]
    assert [row["id"] for row in rest] == [seeded["series_open_id"]]
