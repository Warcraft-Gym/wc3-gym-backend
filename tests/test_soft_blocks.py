"""A player's own soft blocks, and the free time a series' players share.

The seeded open series is P2 (Alpha) against P4 (Beta) in round 1, which runs
from 5 to 11 January 2026. No seeded player has a timezone.
"""

from collections.abc import Callable, Iterator
from typing import Any

import pytest
from httpx2 import Client
from sqlalchemy import event

from app.core.db import Session
from app.models.base import ident
from app.models.match import Match
from app.models.season import Season
from app.models.series import Series
from app.models.user import User
from app.services.availability import NO_SCHEDULING, AvailabilityService
from tests.test_discord_auth import SESSION, stub_clerk

WORK = {"label": "Work", "weekdays": 31, "start_local": "09:00", "end_local": "17:00"}


def set_zone(user_id: int, zone: str | None) -> None:
    with Session.begin() as session:
        user = session.get(User, user_id)
        assert user is not None
        user.timezone = zone


def add_block(client: Client, headers: dict[str, str], **fields: object) -> Any:  # noqa: ANN401  # a JSON body
    resp = client.post("/player-blocks/repeating", json=WORK | fields, headers=headers)
    assert resp.status_code == 201, resp.text
    return resp.json()


def test_a_player_adds_edits_and_deletes_a_repeating_block(
    client: Client, seeded: dict[str, Any], member: Callable[..., dict[str, str]]
) -> None:
    set_zone(seeded["player_ids"][0], "Europe/London")
    headers = member()

    made = add_block(client, headers)
    assert made == WORK | {
        "id": made["id"],
        "start_local": "09:00:00",
        "end_local": "17:00:00",
    }

    resp = client.put(
        f"/player-blocks/repeating/{made['id']}",
        json={"end_local": "17:30", "label": None},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    assert (resp.json()["end_local"], resp.json()["label"]) == ("17:30:00", None)

    listed = client.get("/player-blocks", headers=headers).json()
    assert [row["id"] for row in listed["repeating"]] == [made["id"]]
    assert listed["busy"] == []

    resp = client.delete(f"/player-blocks/repeating/{made['id']}", headers=headers)
    assert resp.status_code == 204, resp.text
    assert client.get("/player-blocks", headers=headers).json()["repeating"] == []


def test_a_player_adds_edits_and_deletes_busy_days(
    client: Client, seeded: dict[str, Any], member: Callable[..., dict[str, str]]
) -> None:
    set_zone(seeded["player_ids"][0], "America/New_York")
    headers = member()

    resp = client.post(
        "/player-blocks/busy",
        json={"label": "Holiday", "first_day": "2026-01-06", "last_day": "2026-01-08"},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    busy_id = resp.json()["id"]

    resp = client.put(
        f"/player-blocks/busy/{busy_id}",
        json={"last_day": "2026-01-09"},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    listed = client.get("/player-blocks", headers=headers).json()
    assert listed["busy"] == [
        {
            "id": busy_id,
            "label": "Holiday",
            "first_day": "2026-01-06",
            "last_day": "2026-01-09",
        }
    ]

    resp = client.delete(f"/player-blocks/busy/{busy_id}", headers=headers)
    assert resp.status_code == 204, resp.text
    assert client.get("/player-blocks", headers=headers).json()["busy"] == []


def test_a_block_needs_a_timezone_first(
    client: Client, seeded: dict[str, Any], member: Callable[..., dict[str, str]]
) -> None:
    resp = client.post("/player-blocks/repeating", json=WORK, headers=member())

    assert resp.status_code == 400, resp.text
    assert resp.json() == {"error": "Set your timezone before you add a block"}


@pytest.mark.parametrize(
    "path,body,error",
    [
        (
            "repeating",
            WORK | {"end_local": "09:00"},
            "A block must end at a different time than it starts",
        ),
        (
            "busy",
            {"first_day": "2026-01-09", "last_day": "2026-01-08"},
            "last_day must not be before first_day",
        ),
    ],
)
def test_an_empty_block_or_a_reversed_range_is_refused(
    client: Client,
    seeded: dict[str, Any],
    member: Callable[..., dict[str, str]],
    path: str,
    body: dict[str, Any],
    error: str,
) -> None:
    set_zone(seeded["player_ids"][0], "Europe/London")

    resp = client.post(f"/player-blocks/{path}", json=body, headers=member())

    assert resp.status_code == 400, resp.text
    assert resp.json() == {"error": error}


@pytest.mark.parametrize(
    "body", [{"weekdays": 0}, {"weekdays": 128}, {"label": "x" * 41}]
)
def test_a_block_outside_the_weekday_bits_or_too_long_a_label_is_refused(
    client: Client,
    seeded: dict[str, Any],
    member: Callable[..., dict[str, str]],
    body: dict[str, Any],
) -> None:
    set_zone(seeded["player_ids"][0], "Europe/London")

    resp = client.post("/player-blocks/repeating", json=WORK | body, headers=member())

    assert resp.status_code == 422, resp.text


def test_an_edit_cannot_null_a_required_field(
    client: Client, seeded: dict[str, Any], member: Callable[..., dict[str, str]]
) -> None:
    set_zone(seeded["player_ids"][0], "Europe/London")
    headers = member()
    made = add_block(client, headers)

    resp = client.put(
        f"/player-blocks/repeating/{made['id']}",
        json={"weekdays": None},
        headers=headers,
    )

    assert resp.status_code == 400, resp.text
    assert resp.json() == {"error": "weekdays cannot be null"}


def test_a_player_cannot_change_another_players_blocks(
    client: Client, seeded: dict[str, Any], member: Callable[..., dict[str, str]]
) -> None:
    set_zone(seeded["player_ids"][0], "Europe/London")
    made = add_block(client, member("1"))
    other = member("2")
    refused = {
        "error": "unauthorized",
        "message": "You can only change your own blocks",
    }

    edit = client.put(
        f"/player-blocks/repeating/{made['id']}", json={"label": "Mine"}, headers=other
    )
    delete = client.delete(f"/player-blocks/repeating/{made['id']}", headers=other)

    assert (edit.status_code, edit.json()) == (403, refused)
    assert (delete.status_code, delete.json()) == (403, refused)
    assert client.get("/player-blocks", headers=other).json()["repeating"] == []
    assert client.get("/player-blocks", headers=member("1")).json()["repeating"] == [
        made
    ]


def test_an_admin_reads_any_players_blocks_and_a_member_does_not(
    client: Client,
    seeded: dict[str, Any],
    member: Callable[..., dict[str, str]],
    auth_headers: dict[str, str],
) -> None:
    player = seeded["player_ids"][0]
    set_zone(player, "Europe/London")
    made = add_block(client, member())

    resp = client.get(f"/users/{player}/blocks", headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"repeating": [made], "busy": []}

    assert client.get(f"/users/{player}/blocks", headers=member("2")).status_code == 403


def free_time(
    client: Client, series_id: int, headers: dict[str, str], **query: str
) -> Any:  # noqa: ANN401  # a JSON body
    resp = client.get(
        f"/player-series/{series_id}/free-time", params=query, headers=headers
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_blank_means_open(
    client: Client, seeded: dict[str, Any], member: Callable[..., dict[str, str]]
) -> None:
    """No zone and no blocks: the whole round is free for both."""
    body = free_time(client, seeded["series_open_id"], member("2"))

    assert body == {
        "start": "2026-01-05T00:00:00Z",
        "end": "2026-01-12T00:00:00Z",
        "hours": 168.0,
        "ranges": [{"start": "2026-01-05T00:00:00Z", "end": "2026-01-12T00:00:00Z"}],
    }


def test_a_player_with_blocks_but_no_timezone_counts_as_free(
    client: Client, seeded: dict[str, Any], member: Callable[..., dict[str, str]]
) -> None:
    p2 = seeded["player_ids"][1]
    set_zone(p2, "Europe/London")
    add_block(client, member("2"), weekdays=127)
    set_zone(p2, None)

    assert free_time(client, seeded["series_open_id"], member("2"))["hours"] == 168.0


def test_the_free_time_hides_whose_block_is_whose(
    client: Client, seeded: dict[str, Any], member: Callable[..., dict[str, str]]
) -> None:
    """The same block on either player gives the same answer, and no label or id."""
    p2, p4 = seeded["player_ids"][1], seeded["player_ids"][3]
    for player in (p2, p4):
        set_zone(player, "Europe/London")
    asleep = {
        "label": "Asleep",
        "weekdays": 127,
        "start_local": "00:00",
        "end_local": "08:00",
    }

    made = add_block(client, member("2"), **asleep)
    on_p2 = client.get(
        f"/player-series/{seeded['series_open_id']}/free-time", headers=member("4")
    )
    client.delete(f"/player-blocks/repeating/{made['id']}", headers=member("2"))
    add_block(client, member("4"), **asleep)
    on_p4 = client.get(
        f"/player-series/{seeded['series_open_id']}/free-time", headers=member("2")
    )

    assert on_p2.json() == on_p4.json()
    assert set(on_p2.json()) == {"start", "end", "hours", "ranges"}
    assert "Asleep" not in on_p2.text
    assert on_p2.json()["hours"] == 7 * 16
    assert on_p2.json()["ranges"][0] == {
        "start": "2026-01-05T08:00:00Z",
        "end": "2026-01-06T00:00:00Z",
    }


def test_a_window_can_be_asked_for(
    client: Client, seeded: dict[str, Any], member: Callable[..., dict[str, str]]
) -> None:
    body = free_time(
        client,
        seeded["series_open_id"],
        member("2"),
        start="2026-03-09T00:00:00Z",
        end="2026-03-10T00:00:00Z",
    )

    assert body["hours"] == 24.0


@pytest.mark.parametrize(
    "query",
    [
        {"start": "2026-03-09T00:00:00Z"},
        {"start": "2026-03-09T00:00:00Z", "end": "2026-03-09T00:00:00Z"},
        {"start": "2026-03-01T00:00:00Z", "end": "2026-04-02T00:00:00Z"},
    ],
)
def test_a_half_empty_or_too_long_window_is_refused(
    client: Client,
    seeded: dict[str, Any],
    member: Callable[..., dict[str, str]],
    query: dict[str, str],
) -> None:
    resp = client.get(
        f"/player-series/{seeded['series_open_id']}/free-time",
        params=query,
        headers=member("2"),
    )

    assert resp.status_code == 400, resp.text


def test_a_player_reads_only_a_series_they_play(
    client: Client, seeded: dict[str, Any], member: Callable[..., dict[str, str]]
) -> None:
    """P3 plays the other series, and captains nothing."""
    resp = client.get(
        f"/player-series/{seeded['series_open_id']}/free-time", headers=member("3")
    )

    assert resp.status_code == 403, resp.text
    assert resp.json() == {"error": "not_authorized_for_this_series"}


def test_an_admin_reads_any_series(
    client: Client, seeded: dict[str, Any], auth_headers: dict[str, str]
) -> None:
    assert free_time(client, seeded["series_open_id"], auth_headers)["hours"] == 168.0


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


def test_a_captain_reads_a_series_of_his_team(
    client: Client, seeded: dict[str, Any], captain: dict[str, str]
) -> None:
    """P1 does not play the open series; P2 plays it for Alpha."""
    assert free_time(client, seeded["series_open_id"], captain)["hours"] == 168.0


def test_a_captain_does_not_read_a_series_of_another_team(
    client: Client, seeded: dict[str, Any], captain: dict[str, str]
) -> None:
    """The same two teams met in another season; P1's seat is this season's."""
    with Session.begin() as session:
        season = Season(name="Other Season", series_per_round=2)
        session.add(season)
        session.flush()
        match = Match(
            team1_id=seeded["team_a_id"],
            team2_id=seeded["team_b_id"],
            season_id=ident(season),
            playday=1,
        )
        session.add(match)
        session.flush()
        series = Series(
            match_id=ident(match),
            player1_id=seeded["player_ids"][1],
            player2_id=seeded["player_ids"][3],
            host_player_id=seeded["player_ids"][1],
        )
        session.add(series)
        session.flush()
        series_id = ident(series)

    resp = client.get(f"/player-series/{series_id}/free-time", headers=captain)

    assert resp.status_code == 403, resp.text


def test_an_event_without_scheduling_refuses_the_free_time(
    client: Client, seeded: dict[str, Any], member: Callable[..., dict[str, str]]
) -> None:
    with Session.begin() as session:
        season = session.get(Season, seeded["season_id"])
        assert season is not None
        season.scheduling_enabled = False

    resp = client.get(
        f"/player-series/{seeded['series_open_id']}/free-time", headers=member("2")
    )

    assert resp.status_code == 403, resp.text
    assert resp.json() == {"error": "scheduling_disabled", "message": NO_SCHEDULING}


@pytest.fixture
def statements() -> Iterator[list[str]]:
    """Every SQL statement the app sends while the test runs."""
    seen: list[str] = []
    with Session() as session:
        engine = session.get_bind()

    def record(conn: object, cursor: object, statement: str, *args: object) -> None:
        seen.append(statement)

    event.listen(engine, "before_cursor_execute", record)
    yield seen
    event.remove(engine, "before_cursor_execute", record)


def test_nothing_writes_the_round_answer(
    client: Client,
    seeded: dict[str, Any],
    member: Callable[..., dict[str, str]],
    statements: list[str],
) -> None:
    """A busy range over the whole round is still only a hint."""
    p2 = seeded["player_ids"][1]
    set_zone(p2, "Europe/London")
    headers = member("2")

    made = add_block(client, headers)
    client.put(
        f"/player-blocks/repeating/{made['id']}", json={"label": "Job"}, headers=headers
    )
    client.post(
        "/player-blocks/busy",
        json={"first_day": "2026-01-05", "last_day": "2026-01-11"},
        headers=headers,
    )
    body = free_time(client, seeded["series_open_id"], headers)
    client.delete(f"/player-blocks/repeating/{made['id']}", headers=headers)

    assert body["hours"] == 0
    assert statements
    assert not [sql for sql in statements if "round_availability" in sql]
    assert AvailabilityService().for_user(p2, seeded["season_id"]) == []
