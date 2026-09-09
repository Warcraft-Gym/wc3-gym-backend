"""A reported result records which side won each game.

The two scores stay the total. A 2-1 fits two orders of games, so the score
alone cannot say who won which map; a row per game says it. A set of games
that does not add up to the score reported is refused.
"""

from collections.abc import Callable
from typing import Any

from httpx2 import Client, Response
from sqlmodel import col, select

from app.core.db import Session
from app.models.series_game import DBSeriesGame


def report(
    client: Client,
    series_id: int,
    headers: dict[str, str],
    p1: int = 2,
    p2: int = 1,
    games: list[dict[str, Any]] | None = None,
) -> Response:
    body: dict[str, Any] = {
        "action": "score_updated",
        "player1_score": p1,
        "player2_score": p2,
    }
    if games is not None:
        body["games"] = games
    return client.put(f"/player-series/{series_id}", headers=headers, json=body)


def won(*sides: str) -> list[dict[str, Any]]:
    """One game per side named, numbered in the order they were played."""
    return [
        {"game_no": game_no, "winner_side": side}
        for game_no, side in enumerate(sides, start=1)
    ]


def stored_games(series_id: int) -> list[tuple[int, str, int | None]]:
    with Session() as session:
        rows = session.scalars(
            select(DBSeriesGame)
            .where(col(DBSeriesGame.series_id) == series_id)
            .order_by(col(DBSeriesGame.game_no))
        )
        return [(row.game_no, row.winner_side, row.map_id) for row in rows]


def test_a_report_records_which_side_won_each_game(
    client: Client,
    seeded: dict[str, Any],
    member: Callable[..., dict[str, str]],
    replay_uploaded: Callable[..., None],
) -> None:
    series_id = seeded["series_open_id"]
    replay_uploaded(series_id, 1, 2, 3)
    resp = report(client, series_id, member("2"), games=won("A", "B", "A"))
    assert resp.status_code == 200, resp.text
    assert stored_games(series_id) == [(1, "A", None), (2, "B", None), (3, "A", None)]
    assert [game["winner_side"] for game in resp.json()["games"]] == ["A", "B", "A"]

    listed = client.get(f"/series/{series_id}/games")
    assert listed.status_code == 200, listed.text
    assert [game["game_no"] for game in listed.json()] == [1, 2, 3]


def test_the_same_score_keeps_the_two_orders_apart(
    client: Client,
    seeded: dict[str, Any],
    member: Callable[..., dict[str, str]],
    replay_uploaded: Callable[..., None],
) -> None:
    """Both reports are 2-1. Only the games say which map the loser took first."""
    series_id = seeded["series_open_id"]
    replay_uploaded(series_id, 1, 2, 3)
    assert (
        report(client, series_id, member("2"), games=won("A", "B", "A")).status_code
        == 200
    )
    first = stored_games(series_id)
    assert (
        report(client, series_id, member("2"), games=won("B", "A", "A")).status_code
        == 200
    )
    assert stored_games(series_id) != first
    assert [side for _, side, _ in stored_games(series_id)] == ["B", "A", "A"]


def test_games_that_do_not_add_up_to_the_score_are_refused(
    client: Client,
    seeded: dict[str, Any],
    member: Callable[..., dict[str, str]],
    replay_uploaded: Callable[..., None],
) -> None:
    series_id = seeded["series_open_id"]
    replay_uploaded(series_id, 1, 2, 3)
    resp = report(client, series_id, member("2"), games=won("A", "A", "A"))
    assert resp.status_code == 400, resp.text
    assert "3-0" in resp.json()["error"] and "2-1" in resp.json()["error"]
    assert stored_games(series_id) == []


def test_a_report_with_too_few_games_is_refused(
    client: Client,
    seeded: dict[str, Any],
    member: Callable[..., dict[str, str]],
    replay_uploaded: Callable[..., None],
) -> None:
    series_id = seeded["series_open_id"]
    replay_uploaded(series_id, 1, 2, 3)
    resp = report(client, series_id, member("2"), games=won("A", "B"))
    assert resp.status_code == 400, resp.text
    assert "3 games" in resp.json()["error"]


def test_the_games_are_numbered_once_each_from_one(
    client: Client,
    seeded: dict[str, Any],
    member: Callable[..., dict[str, str]],
    replay_uploaded: Callable[..., None],
) -> None:
    series_id = seeded["series_open_id"]
    replay_uploaded(series_id, 1, 2, 3)
    twice = [
        {"game_no": 1, "winner_side": "A"},
        {"game_no": 1, "winner_side": "B"},
        {"game_no": 3, "winner_side": "A"},
    ]
    resp = report(client, series_id, member("2"), games=twice)
    assert resp.status_code == 400, resp.text
    assert "numbered 1 to 3" in resp.json()["error"]


def test_a_game_won_by_neither_side_is_refused(
    client: Client,
    seeded: dict[str, Any],
    member: Callable[..., dict[str, str]],
    replay_uploaded: Callable[..., None],
) -> None:
    series_id = seeded["series_open_id"]
    replay_uploaded(series_id, 1, 2, 3)
    games = won("A", "B", "A")
    games[2]["winner_side"] = "C"
    resp = report(client, series_id, member("2"), games=games)
    assert resp.status_code == 400, resp.text
    assert "side A or side B" in resp.json()["error"]


def test_a_game_keeps_the_map_the_report_named(
    client: Client,
    seeded: dict[str, Any],
    member: Callable[..., dict[str, str]],
    replay_uploaded: Callable[..., None],
) -> None:
    series_id, map_id = seeded["series_open_id"], seeded["map_id"]
    replay_uploaded(series_id, 1, 2, 3)
    games = won("A", "B", "A")
    games[0]["map_id"] = map_id
    resp = report(client, series_id, member("2"), games=games)
    assert resp.status_code == 200, resp.text
    assert stored_games(series_id)[0] == (1, "A", map_id)
    assert stored_games(series_id)[1] == (2, "B", None)


def test_a_report_without_games_still_stands(
    client: Client,
    seeded: dict[str, Any],
    member: Callable[..., dict[str, str]],
    replay_uploaded: Callable[..., None],
) -> None:
    """The games are new; a caller that names none still writes its score."""
    series_id = seeded["series_open_id"]
    replay_uploaded(series_id, 1, 2, 3)
    resp = report(client, series_id, member("2"))
    assert resp.status_code == 200, resp.text
    assert resp.json()["player1_score"] == 2
    assert stored_games(series_id) == []
    assert "games" not in resp.json()


def test_a_second_report_replaces_the_games_of_the_first(
    client: Client,
    seeded: dict[str, Any],
    member: Callable[..., dict[str, str]],
    replay_uploaded: Callable[..., None],
) -> None:
    series_id = seeded["series_open_id"]
    replay_uploaded(series_id, 1, 2, 3)
    assert (
        report(client, series_id, member("2"), games=won("A", "B", "A")).status_code
        == 200
    )
    assert (
        report(
            client, series_id, member("2"), p1=2, p2=0, games=won("A", "A")
        ).status_code
        == 200
    )
    assert stored_games(series_id) == [(1, "A", None), (2, "A", None)]


def test_a_deleted_series_drops_its_games(
    client: Client,
    seeded: dict[str, Any],
    member: Callable[..., dict[str, str]],
    auth_headers: dict[str, str],
    replay_uploaded: Callable[..., None],
) -> None:
    series_id = seeded["series_open_id"]
    replay_uploaded(series_id, 1, 2, 3)
    assert (
        report(client, series_id, member("2"), games=won("A", "B", "A")).status_code
        == 200
    )
    assert (
        client.delete(f"/series/{series_id}", headers=auth_headers).status_code == 204
    )
    assert stored_games(series_id) == []
