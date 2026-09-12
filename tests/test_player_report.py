"""A player reports a result from the dashboard once the replays are in the bucket."""

from collections.abc import Callable
from typing import Any

from httpx2 import Client


def test_a_report_with_its_replays_lands(
    client: Client,
    seeded: dict[str, Any],
    member: Callable[..., dict[str, str]],
    replay_uploaded: Callable[..., None],
) -> None:
    replay_uploaded(seeded["series_open_id"], 1, 2)
    resp = client.put(
        f"/player-series/{seeded['series_open_id']}",
        headers=member("2"),
        data={
            "action": "score_updated",
            "player1_score": "2",
            "player2_score": "0",
        },
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert (body["player1_score"], body["player2_score"]) == (2, 0)
    assert [r["game_no"] for r in body["replays"]] == [1, 2]


def test_a_report_needs_one_replay_per_game_played(
    client: Client,
    seeded: dict[str, Any],
    member: Callable[..., dict[str, str]],
    replay_uploaded: Callable[..., None],
) -> None:
    """A 2-1 went three games, so a report with two replays in the bucket is refused."""
    replay_uploaded(seeded["series_open_id"], 1, 2)
    resp = client.put(
        f"/player-series/{seeded['series_open_id']}",
        headers=member("2"),
        data={
            "action": "score_updated",
            "player1_score": "2",
            "player2_score": "1",
        },
    )

    assert resp.status_code == 400, resp.text
    assert resp.json() == {"error": "Game 3 replay is missing"}


def test_a_series_that_is_not_yours_is_refused(
    client: Client, seeded: dict[str, Any], member: Callable[..., dict[str, str]]
) -> None:
    """The open series is P2 against P4, so P1 may not write it."""
    resp = client.put(
        f"/player-series/{seeded['series_open_id']}",
        headers=member("1"),
        data={"date_time": "2026-01-09 20:00:00"},
    )

    assert resp.status_code == 403, resp.text
    assert resp.json() == {"error": "not_authorized_for_this_series"}


def test_a_torn_body_is_a_bad_request(
    client: Client, seeded: dict[str, Any], member: Callable[..., dict[str, str]]
) -> None:
    """A cut-short report is the client's problem, not a server error."""
    resp = client.put(
        f"/player-series/{seeded['series_open_id']}",
        headers=member("2") | {"content-type": "application/json"},
        content=b'{"date_time": "2026-01-09',
    )

    assert resp.status_code == 400, resp.text
    assert resp.json() == {"error": "The body is not valid JSON"}


def test_the_caller_is_checked_before_the_body(
    client: Client, seeded: dict[str, Any]
) -> None:
    """An anonymous caller with a torn body is turned away, not parsed."""
    resp = client.put(
        f"/player-series/{seeded['series_open_id']}",
        headers={"content-type": "application/json"},
        content=b"{not json",
    )

    assert resp.status_code == 401, resp.text


def test_an_empty_body_changes_nothing(
    client: Client, seeded: dict[str, Any], member: Callable[..., dict[str, str]]
) -> None:
    resp = client.put(
        f"/player-series/{seeded['series_open_id']}", headers=member("2"), json={}
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["player1_score"] is None
