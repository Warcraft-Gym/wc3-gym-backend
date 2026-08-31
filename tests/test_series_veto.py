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
    from app.models.relationships import DBMapSeason, DBSeasonWeekMap
    from app.models.season import Season

    with Session() as session:
        season = session.get(Season, seeded["season_id"])
        assert season
        season.pick_ban = "|".join(ORDER)
        season.map_rules = "week,loser,loser"
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
        session.add(DBSeasonWeekMap(season_id=season_id, playday=1, map_id=ids[0]))
        session.commit()
    return ids


def read(client: Client, series_id: int, token: str) -> dict[str, Any]:
    resp = client.get(f"/player-series/{series_id}/veto?token={token}")
    assert resp.status_code == 200, resp.text
    return resp.json()


def write(
    client: Client,
    series_id: int,
    token: str,
    action: str = "step",
    map_id: int | None = None,
) -> Any:  # noqa: ANN401  # a JSON body
    return client.put(
        f"/player-series/{series_id}/veto",
        json={"token": token, "action": action, "map_id": map_id},
    )


def taken(client: Client, series_id: int, token: str, map_id: int) -> dict[str, Any]:
    resp = write(client, series_id, token, map_id=map_id)
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_the_two_players_ban_and_pick_until_the_veto_is_complete(
    client: Client,
    seeded: dict[str, Any],
    pool: list[int],
    dashboard_token: Callable[..., str],
) -> None:
    series_id = seeded["series_open_id"]
    side_a, side_b = dashboard_token(discord_id="2"), dashboard_token(discord_id="4")

    assert read(client, series_id, side_a) == {
        "steps": [],
        "order": ORDER,
        "viewer_side": "A",
        "on_turn": True,
        "complete": False,
        "pool": pool,
        "week_map_id": pool[0],
        "map_rules": "week,loser,loser",
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

    taken(client, series_id, side_a, pool[3])
    body = taken(client, series_id, side_b, pool[4])

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


def test_a_player_cannot_take_the_other_sides_turn(
    client: Client,
    seeded: dict[str, Any],
    pool: list[int],
    dashboard_token: Callable[..., str],
) -> None:
    resp = write(
        client,
        seeded["series_open_id"],
        dashboard_token(discord_id="4"),
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
    dashboard_token: Callable[..., str],
    index: int | None,
    message: str,
) -> None:
    """The week map is game 1, and a map outside the pool is not the season's."""
    map_id = pool[index] if index is not None else 9999

    resp = write(
        client,
        seeded["series_open_id"],
        dashboard_token(discord_id="2"),
        map_id=map_id,
    )

    assert resp.status_code == 400, resp.text
    assert resp.json() == {"error": f"{message}, map id: {map_id}"}


def test_a_map_that_is_gone_cannot_be_taken_again(
    client: Client,
    seeded: dict[str, Any],
    pool: list[int],
    dashboard_token: Callable[..., str],
) -> None:
    """A ban takes its map off the board as much as a pick does."""
    series_id = seeded["series_open_id"]
    taken(client, series_id, dashboard_token(discord_id="2"), pool[1])

    resp = write(client, series_id, dashboard_token(discord_id="4"), map_id=pool[1])

    assert resp.status_code == 400, resp.text
    assert resp.json() == {"error": f"Map already used, map id: {pool[1]}"}


def test_a_player_takes_back_only_their_own_last_step(
    client: Client,
    seeded: dict[str, Any],
    pool: list[int],
    dashboard_token: Callable[..., str],
) -> None:
    series_id = seeded["series_open_id"]
    side_a, side_b = dashboard_token(discord_id="2"), dashboard_token(discord_id="4")

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


def test_an_admin_reads_the_board_and_writes_none_of_it(
    client: Client,
    seeded: dict[str, Any],
    pool: list[int],
    dashboard_token: Callable[..., str],
    auth_headers: dict[str, str],
) -> None:
    series_id = seeded["series_open_id"]
    taken(client, series_id, dashboard_token(discord_id="2"), pool[1])

    resp = client.get(f"/player-series/{series_id}/veto", headers=auth_headers)

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert (body["viewer_side"], body["on_turn"]) == (None, False)
    assert [step["shortname"] for step in body["steps"]] == ["EI"]

    resp = client.put(
        f"/player-series/{series_id}/veto",
        json={"action": "undo"},
        headers=auth_headers,
    )
    assert resp.status_code == 403, resp.text
    assert resp.json() == {"error": "not_authorized_for_this_series"}


def test_a_player_of_another_series_reads_nothing(
    client: Client,
    seeded: dict[str, Any],
    pool: list[int],
    dashboard_token: Callable[..., str],
) -> None:
    """P1 plays the other series of the match, so this board is not theirs."""
    resp = client.get(
        f"/player-series/{seeded['series_open_id']}/veto"
        f"?token={dashboard_token(discord_id='1')}"
    )

    assert resp.status_code == 403, resp.text
    assert resp.json() == {"error": "not_authorized_for_this_series"}
