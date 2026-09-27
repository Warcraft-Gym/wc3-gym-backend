"""GET /events/{event_id}/matches answers a season's matches with scores.

The seeded season holds one match with two series (series_played, series_open).
The same match is embedded on every row of GET /events/{event_id}/series, so
the two routes must agree on its scores and its row shape.
"""

from typing import Any

from httpx2 import Client

from tests.test_events import add_event


def test_matches_answers_the_seasons_match_with_its_scores(
    client: Client, seeded: dict[str, Any]
) -> None:
    resp = client.get(f"/events/{seeded['season_id']}/matches")
    assert resp.status_code == 200, resp.text
    rows = resp.json()
    assert [row["id"] for row in rows] == [seeded["match_id"]]

    series_resp = client.get(f"/events/{seeded['season_id']}/series")
    assert series_resp.status_code == 200, series_resp.text
    embedded = series_resp.json()[0]["match"]
    assert (rows[0]["team1_score"], rows[0]["team2_score"]) == (
        embedded["team1_score"],
        embedded["team2_score"],
    )


def test_matches_row_keys_match_the_series_embedded_match(
    client: Client, seeded: dict[str, Any]
) -> None:
    rows = client.get(f"/events/{seeded['season_id']}/matches").json()
    embedded = client.get(f"/events/{seeded['season_id']}/series").json()[0]["match"]
    assert set(rows[0]) == set(embedded)


def test_an_event_with_no_matches_answers_an_empty_list(client: Client) -> None:
    event_id = add_event()
    resp = client.get(f"/events/{event_id}/matches")
    assert resp.status_code == 200, resp.text
    assert resp.json() == []


def test_matches_carries_the_same_cache_control_as_series(
    client: Client, seeded: dict[str, Any]
) -> None:
    matches_resp = client.get(f"/events/{seeded['season_id']}/matches")
    series_resp = client.get(f"/events/{seeded['season_id']}/series")
    assert matches_resp.headers["cache-control"] == series_resp.headers["cache-control"]
