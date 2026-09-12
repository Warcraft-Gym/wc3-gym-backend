"""The event reads: the computed phase, the event and league pages, the member home.

The phase is never stored. It is read off published, the check-in window, the
round rows and the series, so these tests move those and read the phase back
through the routes.
"""

from datetime import UTC, date, datetime, timedelta
from typing import Any

from httpx2 import Client

from app.core.db import Session
from app.models.enums import EventKind, Race
from app.models.event_division import EventDivision
from app.models.event_entrant import EventEntrant
from app.models.event_stage import EventStage
from app.models.league import League
from app.models.season import Season
from app.services.events import EventService
from tests.test_fantasy_locks import schedule, score

NOW = datetime.now(UTC)


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
    """An unpublished event is a draft; publishing opens signups, the window
    takes it to check-in, and a window that has closed leaves it seeded."""
    event = add_event(published=False)
    assert phase(client, event) == "draft"

    set_fields(event, published=True)
    assert phase(client, event) == "signups_open"

    # A window that has not opened yet is still the signup phase
    set_fields(event, checkin_opens_at=NOW + timedelta(hours=1))
    assert phase(client, event) == "signups_open"

    set_fields(
        event,
        checkin_opens_at=NOW - timedelta(hours=1),
        checkin_closes_at=NOW + timedelta(hours=1),
    )
    assert phase(client, event) == "checkin"

    set_fields(event, checkin_closes_at=NOW - timedelta(minutes=1))
    assert phase(client, event) == "seeded"


def test_an_event_with_signups_closed_and_nothing_generated_is_seeded(
    client: Client,
) -> None:
    assert phase(client, add_event(signups_open=False)) == "seeded"


def test_the_rounds_seed_the_event_and_the_series_run_it(
    client: Client, seeded: dict[str, Any]
) -> None:
    """The seeded league has four rounds and two series, one of them scored."""
    event = seeded["season_id"]
    set_fields(event, end_date=(NOW + timedelta(days=7)).date())
    assert phase(client, event) == "running"

    # No series has started, so only the round rows speak
    score(seeded["series_played_id"], None, None)
    schedule(seeded["series_played_id"], NOW + timedelta(days=1))
    assert phase(client, event) == "seeded"

    schedule(seeded["series_played_id"], NOW - timedelta(hours=1))
    assert phase(client, event) == "running"


def test_an_event_finishes_on_the_last_result_or_the_end_date(
    client: Client, seeded: dict[str, Any]
) -> None:
    event = seeded["season_id"]
    set_fields(event, end_date=(NOW + timedelta(days=7)).date())
    score(seeded["series_open_id"], 2, 0)
    assert phase(client, event) == "finished"

    # A result cleared reopens it, and the end date closes it again
    score(seeded["series_open_id"], None, None)
    assert phase(client, event) == "running"
    set_fields(event, end_date=date(2026, 1, 1))
    assert phase(client, event) == "finished"


def test_the_event_list_carries_every_event_with_its_phase(client: Client) -> None:
    published = add_event(name="Open Cup")
    draft = add_event(name="Hidden Cup", published=False)

    rows = client.get("/events").json()
    assert [(row["id"], row["phase"]) for row in rows] == [
        (published, "signups_open"),
        (draft, "draft"),
    ]


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

    rows = EventService().events_for_member(player)
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
