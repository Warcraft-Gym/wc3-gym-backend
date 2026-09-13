"""The events module: the computed phase, the event and league pages, the writes.

The phase is never stored. It is read off published, the signup flag, the
round rows and the series, so these tests move those and read the phase back
through the routes.
"""

from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any

from httpx2 import Client

from app.core.db import Session
from app.models.enums import EventKind, Race
from app.models.event_division import EventDivision
from app.models.event_entrant import EventEntrant
from app.models.event_stage import EventStage
from app.models.league import League
from app.models.relationships import DBEventRound, round_row
from app.models.season import Season
from app.services.events import EventService
from tests.test_fantasy_locks import schedule, score

NOW = datetime.now(UTC)
TODAY = NOW.date()


def add_event(**fields: Any) -> int:  # noqa: ANN401
    """One event with no rounds and no series."""
    with Session.begin() as session:
        event = Season(
            name=fields.pop("name", "Autumn Cup"), series_per_round=1, **fields
        )
        session.add(event)
        session.flush()
        assert event.id is not None
        return event.id


def add_round(event_id: int, start: date, end: date | None = None) -> None:
    """The first round of an event, so it has a check-in window."""
    with Session.begin() as session:
        session.add(
            DBEventRound(season_id=event_id, number=1, start_date=start, end_date=end)
        )


def set_fields(event_id: int, **fields: Any) -> None:  # noqa: ANN401
    with Session.begin() as session:
        event = session.get(Season, event_id)
        assert event is not None
        event.sqlmodel_update(fields)


def phase(client: Client, event_id: int) -> str:
    response = client.get(f"/events/{event_id}")
    assert response.status_code == 200, response.text
    return response.json()["phase"]


def test_the_phase_walks_the_signup_rungs(client: Client) -> None:
    """An unpublished event is a draft; publishing opens signups, closing them
    with the first round's window open reads check-in, and the rest is seeded."""
    event = add_event(published=False)
    assert phase(client, event) == "draft"

    set_fields(event, published=True)
    assert phase(client, event) == "signups_open"

    # Signups closed and no round to check into rests at seeded
    set_fields(event, signups_open=False)
    assert phase(client, event) == "seeded"

    add_round(event, TODAY + timedelta(days=1), TODAY + timedelta(days=2))
    assert phase(client, event) == "checkin"

    # An event that takes no check-in never reads the rung
    set_fields(event, checkin_enabled=False)
    assert phase(client, event) == "seeded"


def test_the_check_in_rung_reads_the_first_round_window(client: Client) -> None:
    """The window opens checkin_days before the round and a blank one is always open."""
    event = add_event(signups_open=False, checkin_days=3)
    add_round(event, TODAY + timedelta(days=10), TODAY + timedelta(days=11))
    assert phase(client, event) == "seeded"

    set_fields(event, checkin_days=None)
    assert phase(client, event) == "checkin"

    # Past the end of the round the window has closed again
    set_fields(event, checkin_days=3)
    with Session.begin() as session:
        row = round_row(session, event, 1)
        assert row is not None
        row.start_date, row.end_date = (
            TODAY - timedelta(days=5),
            TODAY - timedelta(days=4),
        )
    assert phase(client, event) == "seeded"


def test_open_signups_come_before_the_check_in_rung(
    client: Client, seeded: dict[str, Any]
) -> None:
    """The rounds of a GNL season exist from the day it is created, so a season
    still taking signups reads signups_open, not check-in."""
    event = seeded["season_id"]
    set_fields(event, end_date=TODAY + timedelta(days=7))
    score(seeded["series_played_id"], None, None)
    schedule(seeded["series_played_id"], NOW + timedelta(days=1))
    assert phase(client, event) == "signups_open"


def test_the_rounds_seed_the_event_and_the_series_run_it(
    client: Client, seeded: dict[str, Any]
) -> None:
    """The seeded league has four rounds and two series, one of them scored."""
    event = seeded["season_id"]
    set_fields(event, end_date=TODAY + timedelta(days=7))
    assert phase(client, event) == "running"

    # No series has started, the signups are closed and the rounds are over
    score(seeded["series_played_id"], None, None)
    schedule(seeded["series_played_id"], NOW + timedelta(days=1))
    set_fields(event, signups_open=False)
    assert phase(client, event) == "seeded"

    schedule(seeded["series_played_id"], NOW - timedelta(hours=1))
    assert phase(client, event) == "running"


def test_an_event_finishes_on_the_last_result_or_the_end_date(
    client: Client, seeded: dict[str, Any]
) -> None:
    event = seeded["season_id"]
    set_fields(event, end_date=TODAY + timedelta(days=7))
    score(seeded["series_open_id"], 2, 0)
    assert phase(client, event) == "finished"

    # A result cleared reopens it, and the end date closes it again
    score(seeded["series_open_id"], None, None)
    assert phase(client, event) == "running"
    set_fields(event, end_date=date(2026, 1, 1))
    assert phase(client, event) == "finished"


def test_the_event_list_reads_newest_first_and_filters(client: Client) -> None:
    with Session.begin() as session:
        league = League(name="Gym Cups")
        session.add(league)
        session.flush()
        league_id = league.id
    first = add_event(name="Open Cup")
    draft = add_event(name="Hidden Cup", published=False)
    koth = add_event(name="Night 1", kind=EventKind.koth, league_id=league_id)

    rows = client.get("/events").json()
    assert [(row["id"], row["phase"]) for row in rows] == [
        (koth, "signups_open"),
        (draft, "draft"),
        (first, "signups_open"),
    ]

    assert [row["id"] for row in client.get("/events?published=true").json()] == [
        koth,
        first,
    ]
    assert [row["id"] for row in client.get("/events?kind=koth").json()] == [koth]
    assert [
        row["id"] for row in client.get(f"/events?league_id={league_id}").json()
    ] == [koth]
    assert [row["id"] for row in client.get("/events?limit=1").json()] == [koth]
    assert [row["id"] for row in client.get("/events?offset=2").json()] == [first]


def test_one_event_reads_its_stages_divisions_and_entrants(
    client: Client, seeded: dict[str, Any]
) -> None:
    event = seeded["season_id"]
    with Session.begin() as session:
        session.add_all(
            [
                EventStage(event_id=event, position=2, name="Playoffs", best_of=5),
                EventStage(event_id=event, position=1, name="Groups"),
                EventDivision(
                    event_id=event, position=1, name="Gold", lower_bound=1500
                ),
                EventEntrant(
                    event_id=event, user_id=seeded["player_ids"][0], race=Race.HU
                ),
                EventEntrant(
                    event_id=event,
                    user_id=seeded["player_ids"][1],
                    race=Race.OC,
                    withdrawn_at=NOW,
                ),
            ]
        )

    body = client.get(f"/events/{event}").json()
    assert [stage["name"] for stage in body["stages"]] == ["Groups", "Playoffs"]
    assert [division["name"] for division in body["divisions"]] == ["Gold"]
    # A withdrawn entrant is not counted
    assert body["entrant_count"] == 1
    assert body["kind"] == EventKind.gnl.value


def test_the_list_read_leaves_the_stages_out(client: Client) -> None:
    event = add_event()
    with Session.begin() as session:
        session.add(EventStage(event_id=event, position=1, name="Groups"))

    assert client.get("/events").json()[0]["stages"] == []


def test_an_unknown_event_answers_the_error_envelope(client: Client) -> None:
    response = client.get("/events/404")
    assert response.status_code == 404
    assert response.json() == {"error": "Event not found by id: 404"}


def test_a_league_lists_its_events_newest_first(client: Client) -> None:
    with Session.begin() as session:
        league = League(name="Gym KOTH", short_name="KOTH")
        session.add(league)
        session.flush()
        league_id = league.id
    assert league_id is not None
    first = add_event(name="Night 1", league_id=league_id, kind=EventKind.koth)
    second = add_event(name="Night 2", league_id=league_id, kind=EventKind.koth)
    add_event(name="Unattached Cup")

    leagues = client.get("/leagues").json()
    assert leagues == [
        {
            "id": league_id,
            "name": "Gym KOTH",
            "short_name": "KOTH",
            "page_url": None,
            "kind": "custom",
            "entrant_kind": "solo",
            "events": [],
        }
    ]

    body = client.get(f"/leagues/{league_id}").json()
    assert [event["id"] for event in body["events"]] == [second, first]


def test_an_unknown_league_answers_the_error_envelope(client: Client) -> None:
    response = client.get("/leagues/404")
    assert response.status_code == 404
    assert response.json() == {"error": "League not found by id: 404"}


def test_an_admin_writes_a_league_and_a_reader_cannot(
    client: Client,
    auth_headers: dict[str, str],
    member: Callable[..., dict[str, str]],
) -> None:
    assert client.post("/leagues", json={"name": "Gym Cups"}).status_code == 401
    signed_in = client.post("/leagues", json={"name": "Gym Cups"}, headers=member())
    assert signed_in.status_code == 403, signed_in.text

    created = client.post(
        "/leagues",
        json={"name": "Gym Cups", "short_name": "Cups", "entrant_kind": "solo"},
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    league_id = created.json()["id"]

    updated = client.put(
        f"/leagues/{league_id}",
        json={"short_name": "GC", "page_url": "https://cups"},
        headers=auth_headers,
    )
    assert updated.status_code == 200, updated.text
    assert client.get(f"/leagues/{league_id}").json() == {
        "id": league_id,
        "name": "Gym Cups",
        "short_name": "GC",
        "page_url": "https://cups",
        "kind": "custom",
        "entrant_kind": "solo",
        "events": [],
    }


def test_a_new_event_gets_one_stage_from_its_map_rules(
    client: Client, auth_headers: dict[str, str]
) -> None:
    """A body with no stage list plays one round-robin stage over the event's maps."""
    created = client.post(
        "/events",
        json={
            "name": "Autumn Cup",
            "kind": "cup",
            "region": "EU",
            "map_rules": "veto,loser,loser",
            "starts_at": "2026-10-01T18:00:00Z",
            "description": "One night, single elimination.",
            "page_url": "https://cup",
            "entrant_cap": 32,
            "checkin_enabled": False,
        },
        headers=auth_headers,
    )

    assert created.status_code == 201, created.text
    body = created.json()
    assert body["kind"] == "cup"
    assert body["region"] == "EU"
    assert body["entrant_cap"] == 32
    assert body["checkin_enabled"] is False
    assert body["entrant_count"] == 0
    assert [
        (s["position"], s["format"], s["best_of"], s["map_rules"])
        for s in body["stages"]
    ] == [(1, "round_robin", 3, "veto,loser,loser")]


def test_the_stage_list_is_replaced_in_the_order_of_the_body(
    client: Client, auth_headers: dict[str, str]
) -> None:
    created = client.post(
        "/events",
        json={
            "name": "Winter Cup",
            "stages": [
                {"name": "Groups", "format": "round_robin"},
                {"name": "Playoffs", "format": "single_elimination", "best_of": 5},
            ],
        },
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    event_id = created.json()["id"]
    assert [s["name"] for s in created.json()["stages"]] == ["Groups", "Playoffs"]

    replaced = client.put(
        f"/events/{event_id}/stages",
        json=[{"name": "One night", "format": "single_elimination"}],
        headers=auth_headers,
    )
    assert replaced.status_code == 200, replaced.text
    assert [(s["position"], s["name"]) for s in replaced.json()["stages"]] == [
        (1, "One night")
    ]
    assert client.put(f"/events/{event_id}/stages", json=[]).status_code == 401


def test_an_admin_edits_an_event_and_the_phase_follows(
    client: Client, auth_headers: dict[str, str]
) -> None:
    event = add_event(name="Spring Cup")
    assert phase(client, event) == "signups_open"

    updated = client.put(
        f"/events/{event}",
        json={"published": False, "name": "Spring Cup 2027", "min_games": 20},
        headers=auth_headers,
    )

    assert updated.status_code == 200, updated.text
    assert updated.json()["name"] == "Spring Cup 2027"
    assert updated.json()["min_games"] == 20
    assert phase(client, event) == "draft"
    assert client.put(f"/events/{event}", json={"name": "No"}).status_code == 401


def test_the_writes_answer_the_error_envelope_for_an_unknown_event(
    client: Client, auth_headers: dict[str, str]
) -> None:
    response = client.put("/events/404", json={"name": "Gone"}, headers=auth_headers)
    assert response.status_code == 404
    assert response.json() == {"error": "Event not found by id: 404"}


def test_the_member_home_lists_every_kind_and_marks_what_the_player_joined(
    client: Client, seeded: dict[str, Any]
) -> None:
    """The GNL season, a cup the player entered and one he did not, in one list."""
    from app.models.relationships import DBUserSeasonSignup

    player = seeded["player_ids"][0]
    entered = add_event(
        name="Autumn Cup", kind=EventKind.cup, starts_at=NOW, page_url="https://cup"
    )
    skipped = add_event(name="Winter Cup", kind=EventKind.cup)
    with Session.begin() as session:
        session.add_all(
            [
                EventEntrant(event_id=entered, user_id=player, race=Race.HU),
                DBUserSeasonSignup(
                    user_id=player, season_id=seeded["season_id"], race=Race.HU
                ),
            ]
        )

    add_event(name="Hidden Cup", kind=EventKind.cup, published=False)

    rows = EventService().events_for_member(player)
    # The draft is an admin's own, so the member home does not carry it
    assert [(row.id, row.kind.value, row.joined) for row in rows] == [
        (skipped, "cup", False),
        (entered, "cup", True),
        (seeded["season_id"], "gnl", True),
    ]
    # A cup that carries a time reads its start as the day it runs
    assert rows[1].start == NOW.date()
    assert rows[1].url == "https://cup"
    assert rows[2].start == date(2026, 1, 5)


def test_the_member_home_of_a_player_with_no_id_joins_nothing(
    client: Client, seeded: dict[str, Any]
) -> None:
    rows = EventService().events_for_member(None)
    assert [row.joined for row in rows] == [False]
