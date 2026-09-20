"""The weeks a player says he cannot play.

The player writes his own row from the dashboard and his captain writes the
same row, so the tests drive both paths and check who the row names as its
writer. The seeded season runs four weeks.
"""

from collections.abc import Callable
from datetime import date
from typing import Any

import pytest
from httpx2 import Client

from app.core.db import Session
from app.models.relationships import round_row
from app.models.round_availability import DBRoundAvailability
from app.models.season import Season
from app.models.user import User
from app.models.user_block import UserBusy
from app.models.user_team_season import DBUserTeamSeason
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
            "blocked_out": False,
        }
    ]

    # The answer names the round it is about, the column C2 makes the key
    with Session() as session:
        round_2 = round_row(session, seeded["season_id"], 2)
        row = session.get(DBRoundAvailability, (player_id, seeded["season_id"], 2))
        assert round_2 and row and row.round_id == round_2.id

    rows = write(client, headers, 2, True)
    assert [(row["playday"], row["available"]) for row in rows] == [(2, True)]

    assert write(client, headers, 2, None) == []


def test_a_player_answers_every_week_of_the_season(
    client: Client,
    seeded: dict[str, Any],
    member: Callable[..., dict[str, str]],
    checkin_day: Callable[[str], None],
) -> None:
    """Each round takes its answer on its own days, so the clock moves with them."""
    headers = member()
    write(client, headers, 1, False)
    checkin_day("2026-01-26")
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
    client: Client,
    seeded: dict[str, Any],
    member: Callable[..., dict[str, str]],
    checkin_day: Callable[[str], None],
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

    checkin_day("2026-01-19")
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
    client: Client,
    seeded: dict[str, Any],
    member: Callable[..., dict[str, str]],
    checkin_day: Callable[[str], None],
) -> None:
    headers = member()
    checkin_day("2026-01-19")
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
            "blocked_out": False,
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
            "blocked_out": False,
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


def test_shrinking_the_season_drops_the_answers_past_the_last_round(
    client: Client,
    seeded: dict[str, Any],
    auth_headers: dict[str, str],
    member: Callable[..., dict[str, str]],
    checkin_day: Callable[[str], None],
) -> None:
    """An admin who fixes a round-count typo must not revive the old answers."""
    headers = member()
    season_id = seeded["season_id"]
    checkin_day("2026-01-26")
    assert [row["playday"] for row in write(client, headers, 4, False)] == [4]

    for count in (3, 4):
        resp = client.put(
            f"/seasons/{season_id}", json={"round_count": count}, headers=auth_headers
        )
        assert resp.status_code == 200, resp.text

    checkin_day("2026-01-09")
    assert [row["playday"] for row in write(client, headers, 1, False)] == [1]


def refuse(
    client: Client, headers: dict[str, str], playday: int, available: bool | None
) -> str:
    """The 403 body of a player write outside the round's check-in window."""
    resp = client.put(
        "/player-availability",
        json={"playday": playday, "available": available},
        headers=headers,
    )
    assert resp.status_code == 403, resp.text
    assert resp.json()["error"] == "checkin_closed"
    return resp.json()["message"]


def test_a_player_cannot_check_in_before_the_window_opens(
    client: Client,
    seeded: dict[str, Any],
    member: Callable[..., dict[str, str]],
    checkin_day: Callable[[str], None],
) -> None:
    """Round 2 runs 12 to 18 Jan, so its check-in opens three days before."""
    headers = member()
    checkin_day("2026-01-07")

    assert refuse(client, headers, 2, False) == "Check-in for round 2 opens on 9 Jan."
    assert (
        AvailabilityService().for_user(seeded["player_ids"][0], seeded["season_id"])
        == []
    )

    checkin_day("2026-01-09")
    assert [row["playday"] for row in write(client, headers, 2, False)] == [2]


def test_a_player_cannot_clear_an_answer_before_the_window_opens(
    client: Client,
    seeded: dict[str, Any],
    member: Callable[..., dict[str, str]],
    checkin_day: Callable[[str], None],
) -> None:
    checkin_day("2026-01-07")

    assert refuse(client, member(), 2, None) == "Check-in for round 2 opens on 9 Jan."


def test_a_player_cannot_answer_a_round_that_is_over(
    client: Client,
    seeded: dict[str, Any],
    member: Callable[..., dict[str, str]],
    checkin_day: Callable[[str], None],
) -> None:
    checkin_day("2026-01-19")

    assert refuse(client, member(), 2, False) == "Round 2 is over."


def test_a_captain_answers_outside_the_window(
    client: Client,
    seeded: dict[str, Any],
    captain: dict[str, str],
    checkin_day: Callable[[str], None],
) -> None:
    """The window holds the player only; a captain fills the grid any day."""
    team_id, season_id = seeded["team_a_id"], seeded["season_id"]
    checkin_day("2026-01-07")

    resp = client.put(
        f"/teams/{team_id}/seasons/{season_id}/availability",
        json={"user_id": seeded["player_ids"][1], "playday": 2, "available": False},
        headers=captain,
    )

    assert resp.status_code == 200, resp.text
    rows = AvailabilityService().for_team(team_id, season_id)
    assert [row.playday for row in rows] == [2]


def test_a_season_answers_its_check_in_window_and_takes_a_new_one(
    client: Client, seeded: dict[str, Any], auth_headers: dict[str, str]
) -> None:
    season_id = seeded["season_id"]
    assert client.get(f"/seasons/{season_id}").json()["checkin_days"] == 3

    resp = client.put(
        f"/seasons/{season_id}", json={"checkin_days": 5}, headers=auth_headers
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["checkin_days"] == 5
    assert client.get(f"/seasons/{season_id}").json()["checkin_days"] == 5


def test_a_blank_check_in_window_keeps_the_check_in_open(
    client: Client,
    seeded: dict[str, Any],
    auth_headers: dict[str, str],
    member: Callable[..., dict[str, str]],
    checkin_day: Callable[[str], None],
) -> None:
    """A null window reads back null and takes a player answer on any day."""
    season_id = seeded["season_id"]

    resp = client.put(
        f"/seasons/{season_id}", json={"checkin_days": None}, headers=auth_headers
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["checkin_days"] is None
    listed = {row["id"]: row["checkin_days"] for row in client.get("/seasons").json()}
    assert listed[season_id] is None
    checkin_day("2026-01-07")
    assert [row["playday"] for row in write(client, member(), 2, False)] == [2]


def test_an_event_that_takes_no_check_in_answers_on_any_day(
    client: Client,
    seeded: dict[str, Any],
    member: Callable[..., dict[str, str]],
    checkin_day: Callable[[str], None],
) -> None:
    """checkin_enabled off means the round windows never refuse a player."""
    with Session.begin() as session:
        season = session.get(Season, seeded["season_id"])
        assert season is not None
        season.checkin_enabled = False

    # A day well before round 4 opens, which the window would refuse
    checkin_day("2026-01-07")
    assert [row["playday"] for row in write(client, member(), 4, False)] == [4]


def test_a_negative_check_in_window_is_refused(
    client: Client, seeded: dict[str, Any], auth_headers: dict[str, str]
) -> None:
    created = client.post(
        "/seasons",
        json={"name": "S2", "series_per_round": 2, "checkin_days": -1},
        headers=auth_headers,
    )
    updated = client.put(
        f"/seasons/{seeded['season_id']}",
        json={"checkin_days": -1},
        headers=auth_headers,
    )

    assert created.status_code == 422, created.text
    assert updated.status_code == 422, updated.text


def set_event(season_id: int, **fields: object) -> None:
    """Change the event settings this unit reads."""
    with Session.begin() as session:
        season = session.get(Season, season_id)
        assert season is not None
        for name, value in fields.items():
            setattr(season, name, value)


def busy(user_id: int, zone: str, first: str, last: str) -> None:
    """Give the player a zone and block whole days of it."""
    with Session.begin() as session:
        user = session.get(User, user_id)
        assert user is not None
        user.timezone = zone
        session.add(
            UserBusy(
                user_id=user_id,
                first_day=date.fromisoformat(first),
                last_day=date.fromisoformat(last),
            )
        )


def test_early_check_in_takes_an_answer_before_the_window_opens(
    client: Client, seeded: dict[str, Any], member: Callable[..., dict[str, str]]
) -> None:
    """Round 4 opens on 23 Jan, and the clock stands on 9 Jan."""
    headers = member()

    assert refuse(client, headers, 4, False) == "Check-in for round 4 opens on 23 Jan."

    set_event(seeded["season_id"], early_checkin=True)
    assert [row["playday"] for row in write(client, headers, 4, False)] == [4]


def test_early_check_in_still_refuses_a_round_that_is_over(
    client: Client,
    seeded: dict[str, Any],
    member: Callable[..., dict[str, str]],
    checkin_day: Callable[[str], None],
) -> None:
    set_event(seeded["season_id"], early_checkin=True)
    checkin_day("2026-01-19")

    assert refuse(client, member(), 2, False) == "Round 2 is over."


def test_the_event_zone_says_when_a_round_ends(
    client: Client,
    seeded: dict[str, Any],
    member: Callable[..., dict[str, str]],
    checkin_day: Callable[[str], None],
) -> None:
    """Round 2 ends on 18 Jan, so at UTC midnight on 19 Jan it is over there and
    five hours from over in New York."""
    checkin_day("2026-01-19")
    set_event(seeded["season_id"], round_end_zone="America/New_York")

    assert [row["playday"] for row in write(client, member(), 2, False)] == [2]


def test_blocks_over_a_whole_round_read_as_blocked_out(
    client: Client, seeded: dict[str, Any], member: Callable[..., dict[str, str]]
) -> None:
    """Round 1 runs 5 to 11 January; the answer is derived, never stored."""
    player_id = seeded["player_ids"][0]
    busy(player_id, "Europe/London", "2026-01-05", "2026-01-11")

    rows = client.get("/player-series", headers=member()).json()["availability"]
    assert rows == [
        {
            "user_id": player_id,
            "playday": 1,
            "available": False,
            "set_by_user_id": None,
            "set_by_name": None,
            "blocked_out": True,
        }
    ]
    with Session() as session:
        assert (
            session.get(DBRoundAvailability, (player_id, seeded["season_id"], 1))
            is None
        )


def test_a_stored_answer_wins_over_the_derived_flag(
    client: Client, seeded: dict[str, Any], member: Callable[..., dict[str, str]]
) -> None:
    headers = member()
    busy(seeded["player_ids"][0], "Europe/London", "2026-01-05", "2026-01-11")

    rows = write(client, headers, 1, True)

    assert [(row["playday"], row["available"], row["blocked_out"]) for row in rows] == [
        (1, True, False)
    ]


def test_the_round_window_is_the_events_zone_and_the_blocks_are_the_players(
    client: Client, seeded: dict[str, Any], member: Callable[..., dict[str, str]]
) -> None:
    """Round 1 starts thirteen hours earlier in Auckland than in New York, so a
    player's own days must reach back a day to cover it."""
    player_id = seeded["player_ids"][0]
    set_event(seeded["season_id"], round_end_zone="Pacific/Auckland")
    busy(player_id, "America/New_York", "2026-01-05", "2026-01-11")

    rows = client.get("/player-series", headers=member()).json()["availability"]
    assert rows == []

    busy(player_id, "America/New_York", "2026-01-04", "2026-01-04")
    rows = client.get("/player-series", headers=member()).json()["availability"]
    assert [(row["playday"], row["blocked_out"]) for row in rows] == [(1, True)]


def test_the_team_grid_carries_the_derived_rows(
    client: Client, seeded: dict[str, Any], captain: dict[str, str]
) -> None:
    team_id, season_id = seeded["team_a_id"], seeded["season_id"]
    mate = seeded["player_ids"][1]
    busy(mate, "Europe/London", "2026-01-05", "2026-01-18")

    rows = client.get(
        f"/teams/{team_id}/seasons/{season_id}/availability", headers=captain
    ).json()

    assert [(row["user_id"], row["playday"], row["blocked_out"]) for row in rows] == [
        (mate, 1, True),
        (mate, 2, True),
    ]


def sit_out_all(client: Client, headers: dict[str, str], available: bool | None) -> Any:  # noqa: ANN401  # a JSON body
    resp = client.put(
        "/player-availability/all", json={"available": available}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_a_player_sits_out_every_round_left_and_takes_it_back(
    client: Client, seeded: dict[str, Any], member: Callable[..., dict[str, str]]
) -> None:
    """Early check-in is what opens the rounds past the current window."""
    set_event(seeded["season_id"], early_checkin=True)
    headers = member()

    rows = sit_out_all(client, headers, False)

    assert [(row["playday"], row["available"]) for row in rows] == [
        (1, False),
        (2, False),
        (3, False),
        (4, False),
    ]
    assert {row["set_by_user_id"] for row in rows} == {seeded["player_ids"][0]}
    assert sit_out_all(client, headers, None) == []


def test_sitting_out_every_round_leaves_the_rounds_that_ended(
    client: Client,
    seeded: dict[str, Any],
    member: Callable[..., dict[str, str]],
    checkin_day: Callable[[str], None],
) -> None:
    """Rounds 1 and 2 are over on 19 January."""
    set_event(seeded["season_id"], early_checkin=True)
    checkin_day("2026-01-19")

    rows = sit_out_all(client, member(), False)

    assert [row["playday"] for row in rows] == [3, 4]


def test_a_player_without_early_check_in_cannot_sit_out_every_round(
    client: Client, seeded: dict[str, Any], member: Callable[..., dict[str, str]]
) -> None:
    """Round 3 opens on 16 January and the clock stands on the 9th."""
    resp = client.put(
        "/player-availability/all", json={"available": False}, headers=member()
    )

    assert resp.status_code == 403, resp.text
    assert resp.json() == {
        "error": "checkin_closed",
        "message": "Check-in for round 3 opens on 16 Jan.",
    }
    assert (
        AvailabilityService().for_user(seeded["player_ids"][0], seeded["season_id"])
        == []
    )


def test_a_captain_sits_a_player_out_of_every_round_left(
    client: Client,
    seeded: dict[str, Any],
    captain: dict[str, str],
    checkin_day: Callable[[str], None],
) -> None:
    """The window holds the player only, so the captain needs no early check-in."""
    team_id, season_id = seeded["team_a_id"], seeded["season_id"]
    mate = seeded["player_ids"][1]
    checkin_day("2026-01-07")

    resp = client.put(
        f"/events/{season_id}/teams/{team_id}/availability/all",
        json={"user_id": mate, "available": False},
        headers=captain,
    )

    assert resp.status_code == 200, resp.text
    assert [row["playday"] for row in resp.json()] == [1, 2, 3, 4]
    assert {row["set_by_name"] for row in resp.json()} == {"P1"}


def test_a_captain_cannot_sit_out_a_player_of_another_team(
    client: Client, seeded: dict[str, Any], captain: dict[str, str]
) -> None:
    resp = client.put(
        f"/events/{seeded['season_id']}/teams/{seeded['team_a_id']}/availability/all",
        json={"user_id": seeded["player_ids"][2], "available": False},
        headers=captain,
    )

    assert resp.status_code == 400, resp.text
    assert "not on this team" in resp.json()["error"]


def test_an_event_without_scheduling_refuses_the_bulk_answer(
    client: Client, seeded: dict[str, Any], member: Callable[..., dict[str, str]]
) -> None:
    turn_off_scheduling(seeded["season_id"])

    resp = client.put(
        "/player-availability/all", json={"available": False}, headers=member()
    )

    assert resp.status_code == 403, resp.text
    assert resp.json()["error"] == "scheduling_disabled"


def test_an_admin_sits_a_player_out_of_every_round_left(
    client: Client,
    seeded: dict[str, Any],
    member: Callable[..., dict[str, str]],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """P3 administers the site, so he reaches a team he captains nothing of."""
    headers = member("3")
    monkeypatch.setenv("ADMIN_DISCORD_IDS", "3")

    resp = client.put(
        f"/events/{seeded['season_id']}/teams/{seeded['team_a_id']}/availability/all",
        json={"user_id": seeded["player_ids"][1], "available": False},
        headers=headers,
    )

    assert resp.status_code == 200, resp.text
    assert [row["playday"] for row in resp.json()] == [1, 2, 3, 4]
    assert {row["set_by_user_id"] for row in resp.json()} == {seeded["player_ids"][2]}


def test_a_captain_reaches_only_his_own_team_for_the_bulk_answer(
    client: Client, seeded: dict[str, Any], captain: dict[str, str]
) -> None:
    resp = client.put(
        f"/events/{seeded['season_id']}/teams/{seeded['team_b_id']}/availability/all",
        json={"user_id": seeded["player_ids"][2], "available": False},
        headers=captain,
    )

    assert resp.status_code == 403, resp.text
    assert resp.json() == {"error": "Not your team"}


def test_a_member_cannot_sit_a_player_out_of_every_round(
    client: Client, seeded: dict[str, Any], member: Callable[..., dict[str, str]]
) -> None:
    """P2 captains nothing, so the team route refuses him."""
    resp = client.put(
        f"/events/{seeded['season_id']}/teams/{seeded['team_a_id']}/availability/all",
        json={"user_id": seeded["player_ids"][0], "available": False},
        headers=member("2"),
    )

    assert resp.status_code == 403, resp.text
    assert resp.json() == {"error": "Captains only"}


def test_the_bulk_answer_needs_a_session(
    client: Client, seeded: dict[str, Any]
) -> None:
    resp = client.put("/player-availability/all", json={"available": False})

    assert resp.status_code == 401, resp.text


def out_rounds(client: Client, team_id: int, season_id: int) -> list[list[int]]:
    """The rounds each roster player of the event sits out, in roster order."""
    resp = client.get(f"/events/{season_id}/teams/{team_id}")
    assert resp.status_code == 200, resp.text
    players = resp.json()["player_by_season"][str(season_id)]
    return [
        stat["out_rounds"]
        for player in players
        for stat in player["gnl_stats"]
        if stat["season_id"] == season_id
    ]


def test_the_roster_read_lists_the_rounds_a_player_sits_out(
    client: Client, seeded: dict[str, Any]
) -> None:
    """Round 1 runs 5 to 11 January and round 3 runs 19 to 25 January.

    P1 checks in for round 1, sits out round 2 and has round 3 covered by his
    own busy days; P2 answers nothing.
    """
    team_id, season_id = seeded["team_a_id"], seeded["season_id"]
    player_id, mate = seeded["player_ids"][0], seeded["player_ids"][1]
    service = AvailabilityService()
    service.set(player_id, season_id, 1, True, set_by_user_id=mate)
    service.set(player_id, season_id, 2, False, set_by_user_id=mate)
    busy(player_id, "Europe/London", "2026-01-19", "2026-01-25")

    assert out_rounds(client, team_id, season_id) == [[2, 3], []]


def test_the_roster_read_says_nothing_about_why_a_player_is_out(
    client: Client, seeded: dict[str, Any]
) -> None:
    """The payload carries the rounds alone: no writer, no blocked time."""
    team_id, season_id = seeded["team_a_id"], seeded["season_id"]
    AvailabilityService().set(
        seeded["player_ids"][0],
        season_id,
        2,
        False,
        set_by_user_id=seeded["player_ids"][1],
    )

    stats = client.get(f"/events/{season_id}/teams/{team_id}").json()[
        "player_by_season"
    ][str(season_id)][0]["gnl_stats"][0]

    assert stats["out_rounds"] == [2]
    assert set(stats) == {
        "user_id",
        "team_id",
        "season_id",
        "games",
        "wins",
        "losses",
        "matchup_history",
        "out_rounds",
    }


def test_an_event_without_scheduling_lists_no_sat_out_round(
    client: Client, seeded: dict[str, Any]
) -> None:
    team_id, season_id = seeded["team_a_id"], seeded["season_id"]
    AvailabilityService().set(
        seeded["player_ids"][0],
        season_id,
        2,
        False,
        set_by_user_id=seeded["player_ids"][1],
    )
    turn_off_scheduling(season_id)

    assert out_rounds(client, team_id, season_id) == [[], []]


def test_the_roster_read_costs_a_constant_number_of_statements(
    client: Client, seeded: dict[str, Any]
) -> None:
    """A bigger roster costs the same statements: no query per player."""
    from tests.test_query_budget import count_statements

    team_id, season_id = seeded["team_a_id"], seeded["season_id"]
    # A zoned player takes the derive past its early return, onto blocks and busy days
    busy(seeded["player_ids"][0], "Europe/London", "2026-01-19", "2026-01-25")
    busy(seeded["player_ids"][2], "Europe/London", "2026-01-19", "2026-01-25")
    with count_statements() as small:
        out_rounds(client, team_id, season_id)

    with Session.begin() as session:
        session.add_all(
            DBUserTeamSeason(user_id=user_id, team_id=team_id, season_id=season_id)
            for user_id in seeded["player_ids"][2:]
        )
    with count_statements() as large:
        out_rounds(client, team_id, season_id)

    assert small[0] == large[0]
