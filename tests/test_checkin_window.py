"""The check-in window, measured in minutes from the start.

A dated round opens `checkin_opens_minutes` before its first midnight and
closes when it ends; a cup or a round of a cup opens that many minutes before
it starts and closes at its draw; `checkin_closes_minutes` closes any of them
that many minutes before the start instead. Early check-in takes a player
before the opening, and a runner is never held to the window.
"""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import pytest
from httpx2 import Client

from app.core.db import Session
from app.models.season import Season
from app.services import availability, cup_rounds, events
from app.services.availability import AvailabilityService
from tests.test_availability import refuse, write
from tests.test_cup_recurrence import occur, repeat
from tests.test_event_divisions import enter
from tests.test_event_organizers import CUP, Headers
from tests.test_stage_engine import generate, players

Member = Callable[..., dict[str, str]]

# A one-evening cup that starts at 02:00 UTC on Fri 30 Oct 2026
CUP_START = "2026-10-30T02:00:00Z"
# A cup over two rounds, each with its own start
LEGS = [{"starts_at": "2026-11-06T19:00:00Z"}, {"starts_at": "2026-11-13T19:00:00Z"}]


def at(monkeypatch: pytest.MonkeyPatch, module: Any, moment: str) -> None:  # noqa: ANN401
    """Stop the clock a module reads at `moment`, an ISO time in UTC."""
    instant = datetime.fromisoformat(moment)
    name = "now" if module is availability else "utcnow"
    monkeypatch.setattr(module, name, lambda: instant)


def utc(text: str | None) -> datetime | None:
    return datetime.fromisoformat(text) if text else None


def made(client: Client, headers: Headers, **fields: Any) -> dict[str, Any]:  # noqa: ANN401
    response = client.post("/events", json=CUP | fields, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def edit(client: Client, headers: Headers, event: int, **fields: Any) -> Any:  # noqa: ANN401
    return client.put(f"/events/{event}", json=fields, headers=headers)


def check_in(client: Client, headers: Headers, event: int, entrant: int) -> Any:  # noqa: ANN401
    return client.post(f"/events/{event}/entrants/{entrant}/checkin", headers=headers)


def closed(response: Any) -> str:  # noqa: ANN401
    """The message of a check-in refused outside its window."""
    assert response.status_code == 403, response.text
    assert response.json()["error"] == "checkin_closed"
    return response.json()["message"]


def test_a_round_opens_three_days_before_its_first_midnight_and_closes_at_its_end(
    client: Client,
    seeded: dict[str, Any],
    member: Member,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Round 2 of the seeded season runs Mon 12 to Sun 18 Jan 2026, on a
    season with checkin_days 3, no zone and early check-in off."""
    with Session() as session:
        season = session.get_one(Season, seeded["season_id"])
        assert (
            season.checkin_days,
            season.checkin_opens_minutes,
            season.round_end_zone,
            season.early_checkin,
        ) == (3, 3 * 1440, None, False)
    headers = member()

    at(monkeypatch, availability, "2026-01-08T23:59:00+00:00")
    assert refuse(client, headers, 2, False) == (
        "Check-in for round 2 opens on 9 Jan at 00:00 UTC."
    )
    for moment in ("2026-01-09T00:00:00+00:00", "2026-01-18T23:59:00+00:00"):
        at(monkeypatch, availability, moment)
        assert [row["playday"] for row in write(client, headers, 2, False)] == [2]
    at(monkeypatch, availability, "2026-01-19T00:00:00+00:00")
    assert refuse(client, headers, 2, False) == "Round 2 is over."


def test_an_early_close_shuts_a_round_at_its_start_but_not_for_its_captain(
    client: Client,
    seeded: dict[str, Any],
    member: Member,
    auth_headers: Headers,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """checkin_closes_minutes 0 closes a round at its first midnight; a captain
    writes the same round after it."""
    season, (player, mate) = seeded["season_id"], seeded["player_ids"][:2]
    assert edit(client, auth_headers, season, checkin_closes_minutes=0).is_success

    at(monkeypatch, availability, "2026-01-11T23:59:00+00:00")
    assert [row["playday"] for row in write(client, member(), 2, False)] == [2]
    at(monkeypatch, availability, "2026-01-12T00:00:00+00:00")
    assert refuse(client, member(), 2, True) == (
        "Check-in for round 2 closed on 12 Jan at 00:00 UTC."
    )
    rows = AvailabilityService().set(mate, season, 2, False, set_by_user_id=player)
    assert [row.playday for row in rows] == [2]


def test_every_round_left_skips_the_round_an_early_close_shut(
    client: Client,
    seeded: dict[str, Any],
    member: Member,
    auth_headers: Headers,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """On Wed 14 Jan round 2 is in play and past its close at its first
    midnight, so the write for every round writes rounds 3 and 4 only."""
    season = seeded["season_id"]
    assert edit(
        client, auth_headers, season, checkin_closes_minutes=0, early_checkin=True
    ).is_success
    headers = member()
    at(monkeypatch, availability, "2026-01-11T23:59:00+00:00")
    write(client, headers, 2, True)

    at(monkeypatch, availability, "2026-01-14T12:00:00+00:00")
    for answer, rows in (
        (False, [(2, True), (3, False), (4, False)]),
        (None, [(2, True)]),
    ):
        response = client.put(
            "/player-availability/all", json={"available": answer}, headers=headers
        )
        assert response.status_code == 200, response.text
        assert [(row["playday"], row["available"]) for row in response.json()] == rows


def test_a_dated_round_reads_its_window(client: Client, seeded: dict[str, Any]) -> None:
    """GET /player-series answers the rounds of AvailabilityService, and the
    event read answers the same rounds."""
    opens, closes = datetime(2026, 1, 9, tzinfo=UTC), datetime(2026, 1, 19, tzinfo=UTC)
    rounds = AvailabilityService().season_rounds(seeded["season_id"])
    second = next(row for row in rounds if row.playday == 2)
    assert (second.checkin_opens_at, second.checkin_closes_at) == (opens, closes)

    event = client.get(f"/events/{seeded['season_id']}").json()
    second = next(row for row in event["rounds"] if row["playday"] == 2)
    assert (utc(second["checkin_opens_at"]), utc(second["checkin_closes_at"])) == (
        opens,
        closes,
    )


def test_a_cup_opens_two_hours_before_it_starts_and_closes_at_its_draw(
    client: Client,
    auth_headers: Headers,
    member: Member,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A cup that names no window opens 120 minutes before its start and
    takes a player after it, up to the draw; a runner checks anyone in."""
    cup = made(client, auth_headers, starts_at=CUP_START, checkin_enabled=True)
    assert (
        cup["checkin_opens_minutes"],
        cup["checkin_closes_minutes"],
        cup["checkin_days"],
    ) == (120, None, 0)
    ids = players(4)
    rows = [enter(cup["id"], user_id) for user_id in ids]
    first, second, third, late = rows

    at(monkeypatch, events, "2026-10-29T23:59:00+00:00")
    assert closed(check_in(client, member("90001"), cup["id"], first)) == (
        "Check-in opens on 30 Oct at 00:00 UTC."
    )
    home = {
        row["id"]: row
        for row in client.get("/me/events", headers=member("90001")).json()
    }
    assert (
        home[cup["id"]]["checkin_open"],
        utc(home[cup["id"]]["checkin_opens_at"]),
        home[cup["id"]]["checkin_closes_at"],
    ) == (False, datetime(2026, 10, 30, tzinfo=UTC), None)
    assert check_in(client, auth_headers, cup["id"], second).status_code == 200

    at(monkeypatch, events, "2026-10-30T00:00:00+00:00")
    assert check_in(client, member("90001"), cup["id"], first).status_code == 200
    at(monkeypatch, events, "2026-10-30T02:30:00+00:00")
    assert check_in(client, member("90003"), cup["id"], third).status_code == 200
    read = client.get(f"/events/{cup['id']}").json()
    assert (read["checkin_open"], read["checkin_closes_at"]) == (True, None)

    generate(client, auth_headers, cup["id"], cup["stages"][0]["id"])
    assert closed(check_in(client, member("90004"), cup["id"], late)) == (
        "Check-in closed: the cup is drawn."
    )
    assert client.get(f"/events/{cup['id']}").json()["checkin_open"] is False


def test_early_check_in_takes_a_player_before_the_cup_opens(
    client: Client,
    auth_headers: Headers,
    member: Member,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cup = made(
        client,
        auth_headers,
        starts_at=CUP_START,
        checkin_enabled=True,
        early_checkin=True,
    )
    entrant = enter(cup["id"], players(1)[0])

    at(monkeypatch, events, "2026-10-29T20:00:00+00:00")
    assert check_in(client, member("90001"), cup["id"], entrant).status_code == 200


def test_an_early_close_shuts_the_cup_for_a_player_and_not_for_a_runner(
    client: Client,
    auth_headers: Headers,
    member: Member,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cup = made(client, auth_headers, starts_at=CUP_START, checkin_enabled=True)
    assert edit(client, auth_headers, cup["id"], checkin_closes_minutes=30).is_success
    mine, other = (enter(cup["id"], user_id) for user_id in players(2))
    read = client.get(f"/events/{cup['id']}").json()
    assert utc(read["checkin_closes_at"]) == datetime(2026, 10, 30, 1, 30, tzinfo=UTC)

    at(monkeypatch, events, "2026-10-30T01:31:00+00:00")
    assert closed(check_in(client, member("90001"), cup["id"], mine)) == (
        "Check-in closed on 30 Oct at 01:30 UTC."
    )
    assert check_in(client, auth_headers, cup["id"], other).status_code == 200


def test_a_round_of_a_cup_follows_its_own_start(
    client: Client,
    auth_headers: Headers,
    member: Member,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A cup over rounds opens each round 120 minutes before that round starts;
    it takes early check-in unless the body turns it off."""
    cup = made(client, auth_headers, legs=LEGS)
    assert (cup["checkin_opens_minutes"], cup["early_checkin"]) == (120, True)
    assert edit(client, auth_headers, cup["id"], early_checkin=False).is_success
    entrant = enter(cup["id"], players(1)[0])
    first, second = client.get(f"/events/{cup['id']}").json()["cup_legs"]
    assert [utc(leg["checkin_opens_at"]) for leg in (first, second)] == [
        datetime(2026, 11, 6, 17, tzinfo=UTC),
        datetime(2026, 11, 13, 17, tzinfo=UTC),
    ]

    def leg_check_in(leg: dict[str, Any], headers: Headers, **body: Any) -> Any:  # noqa: ANN401
        return client.post(
            f"/events/{cup['id']}/legs/{leg['id']}/checkins",
            json={"entrant_id": None} | body,
            headers=headers,
        )

    at(monkeypatch, cup_rounds, "2026-11-06T16:59:00+00:00")
    assert closed(leg_check_in(first, member("90001"))) == (
        "Check-in for Round 1 opens on 6 Nov at 17:00 UTC."
    )
    at(monkeypatch, cup_rounds, "2026-11-06T17:00:00+00:00")
    assert leg_check_in(first, member("90001")).status_code == 200
    assert closed(leg_check_in(second, member("90001"))) == (
        "Check-in for Round 2 opens on 13 Nov at 17:00 UTC."
    )
    taken = leg_check_in(second, auth_headers, entrant_id=entrant)
    assert taken.status_code == 200, taken.text


def test_the_days_an_older_client_sends_set_the_minutes(
    client: Client, auth_headers: Headers
) -> None:
    """A body that names checkin_days alone opens that many days in minutes,
    and checkin_days reads the minutes back in whole days."""
    event = client.post(
        "/events", json={"name": "Spring", "checkin_days": 5}, headers=auth_headers
    ).json()
    assert (event["checkin_opens_minutes"], event["checkin_days"]) == (5 * 1440, 5)

    days = edit(client, auth_headers, event["id"], checkin_days=2).json()
    assert (days["checkin_opens_minutes"], days["checkin_days"]) == (2 * 1440, 2)
    minutes = edit(client, auth_headers, event["id"], checkin_opens_minutes=2000).json()
    assert (minutes["checkin_opens_minutes"], minutes["checkin_days"]) == (2000, 1)
    blank = edit(client, auth_headers, event["id"], checkin_days=None).json()
    assert (blank["checkin_opens_minutes"], blank["checkin_days"]) == (None, None)


@pytest.mark.parametrize(
    "fields",
    [
        {"checkin_opens_minutes": -1},
        {"checkin_closes_minutes": -5},
        {"checkin_opens_minutes": 60, "checkin_closes_minutes": 60},
        {"checkin_closes_minutes": 120},
    ],
)
def test_a_window_that_cannot_open_before_it_closes_is_refused(
    client: Client, auth_headers: Headers, fields: dict[str, int]
) -> None:
    """A minute count is 0 or more, and the opening comes before the close,
    against the stored opening when the body names the close alone."""
    cup = made(client, auth_headers, starts_at=CUP_START)
    response = edit(client, auth_headers, cup["id"], **fields)
    assert response.status_code == 422, response.text
    body = CUP | {"name": "Saturday Cup"} | fields
    created = client.post("/events", json=body, headers=auth_headers)
    assert created.status_code == 422, created.text


def test_a_recurring_cup_copies_its_window(
    client: Client, auth_headers: Headers
) -> None:
    _, rule = repeat(
        client, auth_headers, checkin_opens_minutes=90, checkin_closes_minutes=15
    )

    copy = occur(client, auth_headers, rule["id"], "2030-01-11").json()

    assert (copy["checkin_opens_minutes"], copy["checkin_closes_minutes"]) == (90, 15)
