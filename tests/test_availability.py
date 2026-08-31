"""The weeks a player says he cannot play.

The player writes his own row from the dashboard and his captain writes the
same row, so the tests drive both paths and check who the row names as its
writer. The seeded season runs four weeks.
"""

from collections.abc import Callable, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx2 import Client

from tests.test_discord_auth import SESSION, stub_clerk


@pytest.fixture
def dashboard_token() -> Iterator[Callable[..., str]]:
    """A factory for dashboard tokens of a seeded player."""
    from app.api.routes.public import _token_store

    issued: list[str] = []

    def issue(discord_id: str = "1", season_id: int | None = 1) -> str:
        token = f"availability-token-{len(issued)}"
        _token_store[token] = {
            "discord_id": discord_id,
            "discord_tag": f"p{discord_id}",
            "season_id": str(season_id) if season_id else None,
            "access_type": "dashboard",
            "expires_at": datetime.now(UTC) + timedelta(minutes=5),
        }
        issued.append(token)
        return token

    yield issue
    for token in issued:
        _token_store.pop(token, None)


def write(client: Client, token: str, playday: int, available: bool | None) -> Any:  # noqa: ANN401  # a JSON body
    resp = client.put(
        "/player-availability",
        json={"token": token, "playday": playday, "available": available},
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_a_player_answers_a_week_and_takes_it_back(
    client: Client, seeded: dict[str, Any], dashboard_token: Callable[..., str]
) -> None:
    token = dashboard_token()
    player_id = seeded["player_ids"][0]

    rows = write(client, token, 2, False)
    assert rows == [
        {
            "user_id": player_id,
            "playday": 2,
            "available": False,
            "set_by_user_id": player_id,
            "set_by_name": "P1",
        }
    ]

    rows = write(client, token, 2, True)
    assert [(row["playday"], row["available"]) for row in rows] == [(2, True)]

    assert write(client, token, 2, None) == []


def test_a_player_answers_every_week_of_the_season(
    client: Client, seeded: dict[str, Any], dashboard_token: Callable[..., str]
) -> None:
    token = dashboard_token()
    write(client, token, 1, False)
    rows = write(client, token, 4, False)

    assert [row["playday"] for row in rows] == [1, 4]


@pytest.mark.parametrize("playday", [0, 5, -1])
def test_a_week_outside_the_season_is_refused(
    client: Client,
    seeded: dict[str, Any],
    dashboard_token: Callable[..., str],
    playday: int,
) -> None:
    """The seeded season runs four weeks."""
    resp = client.put(
        "/player-availability",
        json={"token": dashboard_token(), "playday": playday, "available": False},
    )

    assert resp.status_code == 400, resp.text
    assert resp.json() == {"error": "playday must be between 1 and 4"}


def test_a_token_without_a_season_falls_back_to_the_setting(
    client: Client, seeded: dict[str, Any], dashboard_token: Callable[..., str]
) -> None:
    from app.core.db import Session
    from app.models.settings import Settings

    with Session() as session:
        session.add(Settings(key="current_gnl_season", value=str(seeded["season_id"])))
        session.commit()

    rows = write(client, dashboard_token(season_id=None), 3, False)

    assert [row["playday"] for row in rows] == [3]


def test_player_series_carries_the_answers_and_the_week_count(
    client: Client, seeded: dict[str, Any], dashboard_token: Callable[..., str]
) -> None:
    token = dashboard_token()
    write(client, token, 3, False)

    body = client.get(f"/player-series?token={token}").json()

    assert body["number_weeks"] == 4
    assert [(row["playday"], row["available"]) for row in body["availability"]] == [
        (3, False)
    ]


def test_player_series_without_a_season_answers_no_availability(
    client: Client, seeded: dict[str, Any], dashboard_token: Callable[..., str]
) -> None:
    body = client.get(f"/player-series?token={dashboard_token(season_id=None)}").json()

    assert body["availability"] == []
    assert body["number_weeks"] is None


@pytest.fixture
def captain(
    client: Client,
    seeded: dict[str, Any],
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, str]:
    """P1 captains Alpha this season, and his session sends these headers."""
    monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
    resp = client.put(
        f"/teams/{seeded['team_a_id']}/seasons/{seeded['season_id']}/captains",
        json={"captain_ids": [seeded["player_ids"][0]]},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text

    stub_clerk(monkeypatch, account={"id": "1", "username": "p1", "avatar": None})
    return SESSION


def test_a_captain_answers_for_a_player_of_his_team(
    client: Client, seeded: dict[str, Any], captain: dict[str, str]
) -> None:
    team_id, season_id = seeded["team_a_id"], seeded["season_id"]
    mate = seeded["player_ids"][1]

    resp = client.put(
        f"/teams/{team_id}/seasons/{season_id}/availability",
        json={"user_id": mate, "playday": 1, "available": False},
        headers=captain,
    )

    assert resp.status_code == 200, resp.text
    assert resp.json() == [
        {
            "user_id": mate,
            "playday": 1,
            "available": False,
            "set_by_user_id": seeded["player_ids"][0],
            "set_by_name": "P1",
        }
    ]

    listed = client.get(
        f"/teams/{team_id}/seasons/{season_id}/availability", headers=captain
    )
    assert listed.status_code == 200, listed.text
    assert [row["user_id"] for row in listed.json()] == [mate]


def test_a_captain_cannot_answer_for_another_team(
    client: Client, seeded: dict[str, Any], captain: dict[str, str]
) -> None:
    """P3 plays for Beta, so Alpha's captain does not write his weeks."""
    resp = client.put(
        f"/teams/{seeded['team_a_id']}/seasons/{seeded['season_id']}/availability",
        json={"user_id": seeded["player_ids"][2], "playday": 1, "available": False},
        headers=captain,
    )

    assert resp.status_code == 400, resp.text
    assert "not on this team" in resp.json()["error"]


def test_a_captain_reaches_only_his_own_team(
    client: Client, seeded: dict[str, Any], captain: dict[str, str]
) -> None:
    resp = client.get(
        f"/teams/{seeded['team_b_id']}/seasons/{seeded['season_id']}/availability",
        headers=captain,
    )

    assert resp.status_code == 403, resp.text
    assert resp.json() == {"error": "Captains only"}


def test_the_player_writes_over_his_captains_answer(
    client: Client,
    seeded: dict[str, Any],
    captain: dict[str, str],
    dashboard_token: Callable[..., str],
) -> None:
    """One row per week, so the last writer holds it."""
    mate = seeded["player_ids"][1]
    client.put(
        f"/teams/{seeded['team_a_id']}/seasons/{seeded['season_id']}/availability",
        json={"user_id": mate, "playday": 1, "available": False},
        headers=captain,
    )

    rows = write(client, dashboard_token(discord_id="2"), 1, True)

    assert rows == [
        {
            "user_id": mate,
            "playday": 1,
            "available": True,
            "set_by_user_id": mate,
            "set_by_name": "P2",
        }
    ]
