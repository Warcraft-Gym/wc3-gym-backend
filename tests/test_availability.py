"""The weeks a player says he cannot play.

The player writes his own row from the dashboard and his captain writes the
same row, so the tests drive both paths and check who the row names as its
writer. The seeded season runs four weeks.
"""

from collections.abc import Callable
from typing import Any

import pytest
from httpx2 import Client

from app.core.db import Session
from app.models.relationships import round_row
from app.models.round_availability import DBRoundAvailability
from app.models.season import Season
from app.services.availability import AvailabilityService
from tests.test_discord_auth import SESSION, stub_clerk


def write(
    client: Client, headers: dict[str, str], playday: int, available: bool | None
) -> Any:  # noqa: ANN401  # a JSON body
    resp = client.put(
        "/player-availability",
        json={"playday": playday, "available": available},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_a_player_answers_a_week_and_takes_it_back(
    client: Client, seeded: dict[str, Any], member: Callable[..., dict[str, str]]
) -> None:
    headers = member()
    player_id = seeded["player_ids"][0]

    rows = write(client, headers, 2, False)
    assert rows == [
        {
            "user_id": player_id,
            "playday": 2,
            "available": False,
            "set_by_user_id": player_id,
            "set_by_name": "P1",
        }
    ]

    # The answer is keyed by the player and the round it is about
    with Session() as session:
        round_2 = round_row(session, seeded["season_id"], 2)
        assert round_2 and round_2.id
        row = session.get(DBRoundAvailability, (player_id, round_2.id))
        assert row and row.playday == 2

    rows = write(client, headers, 2, True)
    assert [(row["playday"], row["available"]) for row in rows] == [(2, True)]

    assert write(client, headers, 2, None) == []


def test_a_player_answers_every_week_of_the_season(
    client: Client, seeded: dict[str, Any], member: Callable[..., dict[str, str]]
) -> None:
    headers = member()
    write(client, headers, 1, False)
    rows = write(client, headers, 4, False)

    assert [row["playday"] for row in rows] == [1, 4]


@pytest.mark.parametrize("playday", [0, 5, -1])
def test_a_week_outside_the_season_is_refused(
    client: Client,
    seeded: dict[str, Any],
    member: Callable[..., dict[str, str]],
    playday: int,
) -> None:
    """The seeded season runs four weeks."""
    resp = client.put(
        "/player-availability",
        json={"playday": playday, "available": False},
        headers=member(),
    )

    assert resp.status_code == 400, resp.text
    assert resp.json() == {"error": "playday must be between 1 and 4"}


def test_the_week_lands_in_the_season_the_setting_names(
    client: Client, seeded: dict[str, Any], member: Callable[..., dict[str, str]]
) -> None:
    """A newer season exists and the setting names the older one.

    With one season the fallback to the highest season id answers the same, so
    the setting is unproven. The newer season carries no rounds, so a week is
    refused there and accepted in the season the setting names.
    """
    from app.core.db import Session
    from app.models.season import Season
    from app.models.settings import Settings

    with Session() as session:
        session.add(Season(name="Later Season", series_per_round=2))
        session.add(Settings(key="current_gnl_season", value=str(seeded["season_id"])))
        session.commit()

    rows = write(client, member(), 3, False)
    assert [row["playday"] for row in rows] == [3]

    refused = client.put(
        "/player-availability",
        json={"playday": 6, "available": False},
        headers=member(),
    )
    assert refused.status_code == 400, refused.text
    assert refused.json() == {"error": "playday must be between 1 and 4"}


def test_player_series_carries_the_answers_and_the_rounds(
    client: Client, seeded: dict[str, Any], member: Callable[..., dict[str, str]]
) -> None:
    headers = member()
    write(client, headers, 3, False)

    body = client.get("/player-series", headers=headers).json()

    assert body["round_count"] == 4
    assert [(row["playday"], row["available"]) for row in body["availability"]] == [
        (3, False)
    ]
    assert [(row["playday"], row["start_date"]) for row in body["rounds"]] == [
        (1, "2026-01-05"),
        (2, "2026-01-12"),
        (3, "2026-01-19"),
        (4, "2026-01-26"),
    ]


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
    assert resp.json() == {"error": "Not your team"}


def test_the_player_writes_over_his_captains_answer(
    client: Client,
    seeded: dict[str, Any],
    captain: dict[str, str],
    member: Callable[..., dict[str, str]],
) -> None:
    """One row per week, so the last writer holds it."""
    mate = seeded["player_ids"][1]
    client.put(
        f"/teams/{seeded['team_a_id']}/seasons/{seeded['season_id']}/availability",
        json={"user_id": mate, "playday": 1, "available": False},
        headers=captain,
    )

    rows = write(client, member("2"), 1, True)

    assert rows == [
        {
            "user_id": mate,
            "playday": 1,
            "available": True,
            "set_by_user_id": mate,
            "set_by_name": "P2",
        }
    ]


def test_an_event_without_scheduling_refuses_the_answer(
    client: Client, seeded: dict[str, Any], member: Callable[..., dict[str, str]]
) -> None:
    turn_off_scheduling(seeded["season_id"])

    resp = client.put(
        "/player-availability",
        json={"playday": 2, "available": False},
        headers=member(),
    )

    assert resp.status_code == 403, resp.text
    assert resp.json()["error"] == "scheduling_disabled"
    assert (
        AvailabilityService().for_user(seeded["player_ids"][0], seeded["season_id"])
        == []
    )


def test_an_event_without_scheduling_refuses_the_captain(
    client: Client, seeded: dict[str, Any], captain: dict[str, str]
) -> None:
    team_id, season_id = seeded["team_a_id"], seeded["season_id"]
    turn_off_scheduling(season_id)

    resp = client.put(
        f"/teams/{team_id}/seasons/{season_id}/availability",
        json={"user_id": seeded["player_ids"][1], "playday": 1, "available": False},
        headers=captain,
    )

    assert resp.status_code == 403, resp.text
    assert resp.json()["error"] == "scheduling_disabled"
    assert AvailabilityService().for_team(team_id, season_id) == []


def turn_off_scheduling(season_id: int) -> None:
    with Session.begin() as session:
        season = session.get(Season, season_id)
        assert season is not None
        season.scheduling_enabled = False
