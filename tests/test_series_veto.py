"""The map veto of a series, taken step by step by its two players.

The board is derived from the season: pick_ban names the order, the pool names
the maps, and the week rule keeps the playday's map out of the veto because it
is already game 1. The seeded open series is P2 (side A) against P4 (side B).
"""

from collections.abc import Callable
from typing import Any

import pytest
from httpx2 import Client

ORDER = ["Ban_A", "Ban_B", "Pick_A", "Pick_B"]


@pytest.fixture
def pool(seeded: dict[str, Any]) -> list[int]:
    """A five map pool, an ABBA order, and CH as the map of week 1."""
    from app.core.db import Session
    from app.models.base import ident
    from app.models.map import Map
    from app.models.relationships import DBMapSeason, round_row
    from app.models.season import Season

    with Session() as session:
        season = session.get(Season, seeded["season_id"])
        assert season
        season.pick_ban = "|".join(ORDER)
        season.map_rules = "fixed,loser,loser"
        maps = [Map(name=short, shortname=short) for short in ("EI", "TS", "LR", "AL")]
        session.add_all(maps)
        session.flush()
        season_id = ident(season)
        ids = [int(seeded["map_id"]), *[ident(map) for map in maps]]
        session.add_all(
            [
                DBMapSeason(map_id=map_id, season_id=season_id, position=position)
                for position, map_id in enumerate(ids[1:], start=1)
            ]
        )
        round_one = round_row(session, season_id, 1)
        assert round_one
        round_one.map_id = ids[0]
        session.commit()
    return ids


def read(client: Client, series_id: int, headers: dict[str, str]) -> dict[str, Any]:
    resp = client.get(f"/player-series/{series_id}/veto", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def write(
    client: Client,
    series_id: int,
    headers: dict[str, str],
    action: str = "step",
    map_id: int | None = None,
) -> Any:  # noqa: ANN401  # a JSON body
    return client.put(
        f"/player-series/{series_id}/veto",
        json={"action": action, "map_id": map_id},
        headers=headers,
    )


def taken(
    client: Client, series_id: int, headers: dict[str, str], map_id: int
) -> dict[str, Any]:
    resp = write(client, series_id, headers, map_id=map_id)
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_the_two_players_ban_and_pick_until_the_veto_is_complete(
    client: Client,
    seeded: dict[str, Any],
    pool: list[int],
    member: Callable[..., dict[str, str]],
) -> None:
    series_id = seeded["series_open_id"]
    side_a, side_b = member("2"), member("4")

    assert read(client, series_id, side_a) == {
        "steps": [],
        "order": ORDER,
        "viewer_side": "A",
        "on_turn": True,
        "complete": False,
        "pool": pool,
        "week_map_id": pool[0],
        "map_rules": "fixed,loser,loser",
        "player1": {"id": seeded["player_ids"][1], "name": "P2"},
        "player2": {"id": seeded["player_ids"][3], "name": "P4"},
    }

    body = taken(client, series_id, side_a, pool[1])
    assert body["steps"] == [
        {
            "step_no": 1,
            "side": "A",
            "action": "ban",
            "map_id": pool[1],
            "entered_by": seeded["player_ids"][1],
            "shortname": "EI",
            "name": "EI",
        }
    ]
    assert (body["viewer_side"], body["on_turn"], body["complete"]) == (
        "A",
        False,
        False,
    )

    body = taken(client, series_id, side_b, pool[2])
    assert (body["viewer_side"], body["on_turn"]) == ("B", False)

    # A's pick leaves one map to the one entry left, so B's pick applies itself
    body = taken(client, series_id, side_a, pool[3])

    assert [
        (step["side"], step["action"], step["shortname"]) for step in body["steps"]
    ] == [
        ("A", "ban", "EI"),
        ("B", "ban", "TS"),
        ("A", "pick", "LR"),
        ("B", "pick", "AL"),
    ]
    assert (body["complete"], body["on_turn"]) == (True, False)

    # The order is walked out, so no step is left to take
    resp = write(client, series_id, side_a, map_id=pool[0])
    assert resp.status_code == 400, resp.text
    assert resp.json() == {"error": "The veto is complete"}


def test_a_pick_with_maps_to_spare_forces_nothing(
    client: Client,
    seeded: dict[str, Any],
    pool: list[int],
    member: Callable[..., dict[str, str]],
) -> None:
    from app.core.db import Session
    from app.models.season import Season

    with Session.begin() as session:
        season = session.get(Season, seeded["season_id"])
        assert season
        season.pick_ban = "Pick_A|Pick_B"

    series_id = seeded["series_open_id"]
    body = taken(client, series_id, member("2"), pool[1])

    # Three maps are left to B's one entry, so B still chooses
    assert [step["side"] for step in body["steps"]] == ["A"]
    assert body["complete"] is False


def test_a_player_cannot_take_the_other_sides_turn(
    client: Client,
    seeded: dict[str, Any],
    pool: list[int],
    member: Callable[..., dict[str, str]],
) -> None:
    resp = write(
        client,
        seeded["series_open_id"],
        member("4"),
        map_id=pool[1],
    )

    assert resp.status_code == 400, resp.text
    assert resp.json() == {"error": "It is not your turn"}


@pytest.mark.parametrize(
    "index,message", [(0, "Map played as game 1"), (None, "Map not part of the season")]
)
def test_a_map_off_the_board_is_refused(
    client: Client,
    seeded: dict[str, Any],
    pool: list[int],
    member: Callable[..., dict[str, str]],
    index: int | None,
    message: str,
) -> None:
    """The week map is game 1, and a map outside the pool is not the season's."""
    map_id = pool[index] if index is not None else 9999

    resp = write(
        client,
        seeded["series_open_id"],
        member("2"),
        map_id=map_id,
    )

    assert resp.status_code == 400, resp.text
    assert resp.json() == {"error": f"{message}, map id: {map_id}"}


def test_a_map_that_is_gone_cannot_be_taken_again(
    client: Client,
    seeded: dict[str, Any],
    pool: list[int],
    member: Callable[..., dict[str, str]],
) -> None:
    """A ban takes its map off the board as much as a pick does."""
    series_id = seeded["series_open_id"]
    taken(client, series_id, member("2"), pool[1])

    resp = write(client, series_id, member("4"), map_id=pool[1])

    assert resp.status_code == 400, resp.text
    assert resp.json() == {"error": f"Map already used, map id: {pool[1]}"}


def test_a_player_takes_back_only_their_own_last_step(
    client: Client,
    seeded: dict[str, Any],
    pool: list[int],
    member: Callable[..., dict[str, str]],
) -> None:
    series_id = seeded["series_open_id"]
    side_a, side_b = member("2"), member("4")

    taken(client, series_id, side_a, pool[1])
    resp = write(client, series_id, side_a, action="undo")
    assert resp.status_code == 200, resp.text
    assert resp.json()["steps"] == []
    assert resp.json()["on_turn"] is True

    # The other side has moved since, so the last step is theirs to take back
    taken(client, series_id, side_a, pool[1])
    taken(client, series_id, side_b, pool[2])
    resp = write(client, series_id, side_a, action="undo")

    assert resp.status_code == 400, resp.text
    assert resp.json() == {"error": "The last step is not yours to take back"}


def test_one_player_records_a_veto_that_happened_elsewhere(
    client: Client,
    seeded: dict[str, Any],
    pool: list[int],
    member: Callable[..., dict[str, str]],
) -> None:
    """A veto done in a chat is typed in by one player for both sides, in the
    season's order, and every step names who entered it."""
    series_id = seeded["series_open_id"]
    side_b = member("4")

    # B enters A's ban, out of turn for a live step
    resp = write(client, series_id, side_b, action="record", map_id=pool[1])
    assert resp.status_code == 200, resp.text
    assert [(step["side"], step["entered_by"]) for step in resp.json()["steps"]] == [
        ("A", seeded["player_ids"][3])
    ]

    # The step entered for the other side is the enterer's to take back
    resp = write(client, series_id, side_b, action="undo")
    assert resp.status_code == 200, resp.text
    assert resp.json()["steps"] == []

    for map_id in (pool[1], pool[2]):
        resp = write(client, series_id, side_b, action="record", map_id=map_id)
        assert resp.status_code == 200, resp.text
    resp = write(client, series_id, side_b, action="record", map_id=pool[3])
    assert resp.status_code == 200, resp.text
    body = resp.json()

    # The rules of a live veto hold, and the forced final step names nobody
    assert [
        (step["side"], step["action"], step["shortname"], step["entered_by"])
        for step in body["steps"]
    ] == [
        ("A", "ban", "EI", seeded["player_ids"][3]),
        ("B", "ban", "TS", seeded["player_ids"][3]),
        ("A", "pick", "LR", seeded["player_ids"][3]),
        ("B", "pick", "AL", None),
    ]
    assert body["complete"] is True

    resp = write(client, series_id, side_b, action="record", map_id=pool[0])
    assert resp.status_code == 400, resp.text
    assert resp.json() == {"error": "The veto is complete"}

    # The forced step goes with the step that forced it, on the enterer's undo
    resp = write(client, series_id, side_b, action="undo")
    assert resp.status_code == 200, resp.text
    assert [step["shortname"] for step in resp.json()["steps"]] == ["EI", "TS"]
    assert resp.json()["complete"] is False


def test_an_admin_enters_any_side_and_takes_back_any_step(
    client: Client,
    seeded: dict[str, Any],
    pool: list[int],
    member: Callable[..., dict[str, str]],
    auth_headers: dict[str, str],
) -> None:
    """The match page lets an admin fix a veto: no side, no turn."""
    series_id = seeded["series_open_id"]
    taken(client, series_id, member("2"), pool[1])

    resp = client.get(f"/player-series/{series_id}/veto", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert (resp.json()["viewer_side"], resp.json()["on_turn"]) == (None, False)

    # The admin enters the step the order names next, side B; the admin token has no player row
    resp = client.put(
        f"/player-series/{series_id}/veto",
        json={"action": "step", "map_id": pool[2]},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    steps = resp.json()["steps"]
    assert [(s["side"], s["shortname"]) for s in steps] == [("A", "EI"), ("B", "TS")]
    assert steps[0]["entered_by"] is not None
    assert steps[1]["entered_by"] is None

    # And takes back a step a player took
    resp = client.put(
        f"/player-series/{series_id}/veto",
        json={"action": "undo"},
        headers=auth_headers,
    )
    resp = client.put(
        f"/player-series/{series_id}/veto",
        json={"action": "undo"},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["steps"] == []
    resp = client.put(
        f"/player-series/{series_id}/veto",
        json={"action": "undo"},
        headers=auth_headers,
    )
    assert resp.status_code == 400, resp.text


def test_a_player_of_another_series_reads_nothing(
    client: Client,
    seeded: dict[str, Any],
    pool: list[int],
    member: Callable[..., dict[str, str]],
) -> None:
    """P1 plays the other series of the match, so this board is not theirs."""
    resp = client.get(
        f"/player-series/{seeded['series_open_id']}/veto", headers=member("1")
    )

    assert resp.status_code == 403, resp.text
    assert resp.json() == {"error": "not_authorized_for_this_series"}


def test_a_result_says_whether_its_veto_is_complete(
    client: Client,
    seeded: dict[str, Any],
    pool: list[int],
    member: Callable[..., dict[str, str]],
    replay_uploaded: Callable[..., None],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The record is what the map stats are made of, so every answer says
    whether the veto is there. It never refuses the result."""
    series_id = seeded["series_open_id"]
    side_a, side_b = member("2"), member("4")
    replay_uploaded(series_id, 1, 2)
    scores = {
        "action": "score_updated",
        "player1_score": "2",
        "player2_score": "0",
    }

    # An incomplete veto never holds a result back; the answer says it is missing
    resp = client.put(f"/player-series/{series_id}", data=scores, headers=side_a)
    assert resp.status_code == 200, resp.text
    assert resp.json()["veto_complete"] is False

    resp = client.put(
        f"/player-series/{series_id}",
        json={"date_time": "2026-09-05 18:00:00"},
        headers=side_a,
    )
    assert resp.status_code == 200, resp.text

    taken(client, series_id, side_a, pool[1])
    taken(client, series_id, side_b, pool[2])
    taken(client, series_id, side_a, pool[3])
    resp = client.put(f"/player-series/{series_id}", data=scores, headers=side_a)
    assert resp.status_code == 200, resp.text
    assert resp.json()["veto_complete"] is True
    assert (resp.json()["player1_score"], resp.json()["player2_score"]) == (2, 0)


def test_an_admin_who_plays_is_named_on_the_steps_they_enter(
    client: Client,
    seeded: dict[str, Any],
    pool: list[int],
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """An admin with a player row enters both sides; every step they take names them."""
    from tests.test_discord_auth import _grant
    from tests.test_player_session import member_session

    _grant(client, auth_headers, "2")
    headers = member_session(monkeypatch, discord_id="2")
    series_id = seeded["series_open_id"]

    # The board knows the side they play, so their own turn is a player's turn
    resp = client.get(f"/player-series/{series_id}/veto", headers=headers)
    assert resp.status_code == 200, resp.text
    assert (resp.json()["viewer_side"], resp.json()["on_turn"]) == ("A", True)

    for map_id in (pool[1], pool[2], pool[3]):
        resp = client.put(
            f"/player-series/{series_id}/veto",
            json={"action": "step", "map_id": map_id},
            headers=headers,
        )
        assert resp.status_code == 200, resp.text

    steps = resp.json()["steps"]
    assert [(s["side"], s["action"]) for s in steps] == [
        ("A", "ban"),
        ("B", "ban"),
        ("A", "pick"),
        ("B", "pick"),
    ]
    assert [s["entered_by"] for s in steps] == [seeded["player_ids"][1]] * 3 + [None]
    assert (resp.json()["viewer_side"], resp.json()["on_turn"]) == ("A", False)


def test_the_series_row_names_the_map_each_side_picked(
    client: Client,
    seeded: dict[str, Any],
    pool: list[int],
    member: Callable[..., dict[str, str]],
) -> None:
    """The series card reads the picks off the series, never the whole board."""
    series_id = seeded["series_open_id"]
    side_a, side_b = member("2"), member("4")

    body = client.get("/player-series", headers=side_a).json()
    row = next(s for s in body["series"] if s["id"] == series_id)
    assert (row["player1_pick_map"], row["player2_pick_map"]) == (None, None)

    taken(client, series_id, side_a, pool[1])
    taken(client, series_id, side_b, pool[2])
    # A's pick leaves one map to the one entry left, so B's pick applies itself
    taken(client, series_id, side_a, pool[3])

    body = client.get("/player-series", headers=side_a).json()
    row = next(s for s in body["series"] if s["id"] == series_id)
    assert (row["player1_pick_map"], row["player2_pick_map"]) == ("LR", "AL")
