"""The events module: the computed phase, the event and league pages, the writes.

The phase is never stored. It is read off published, the signup flag, the
round rows and the series, so these tests move those and read the phase back
through the routes.
"""

from collections.abc import Callable
from datetime import UTC, date, datetime, timedelta
from typing import Any

import pytest
from httpx2 import Client
from sqlmodel import col, select

from app.core.db import Session
from app.models.base import ident
from app.models.enums import EntrantKind, EventKind, Race
from app.models.event_division import EventDivision
from app.models.event_entrant import EventEntrant
from app.models.event_stage import EventStage
from app.models.league import League
from app.models.relationships import DBEventRound, round_row
from app.models.round_availability import DBRoundAvailability
from app.models.season import Season
from app.models.user import User
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


def phase(client: Client, event_id: int, headers: dict[str, str] | None = None) -> str:
    """The phase the event reads back; a draft needs the admin headers."""
    response = client.get(f"/events/{event_id}", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["phase"]


def test_the_phase_walks_the_signup_rungs(
    client: Client, auth_headers: dict[str, str]
) -> None:
    """An unpublished event is a draft; publishing opens signups, closing them
    with the first round's window open reads check-in, and the rest is seeded."""
    event = add_event(published=False)
    assert phase(client, event, auth_headers) == "draft"

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


def test_an_event_that_played_nothing_finishes_on_the_day_it_starts(
    client: Client,
) -> None:
    """A night closed with nothing played holds no series, so the day it starts
    on ends it; a night still to come is taking its check-in."""
    over = add_event(
        name="Night 1",
        kind=EventKind.koth,
        starts_at=NOW - timedelta(days=1),
        signups_open=False,
    )
    assert phase(client, over) == "finished"

    later = add_event(
        name="Night 2",
        kind=EventKind.koth,
        starts_at=NOW + timedelta(days=1),
        signups_open=False,
    )
    assert phase(client, later) == "checkin"


def test_the_event_list_reads_newest_first_and_filters(
    client: Client, auth_headers: dict[str, str]
) -> None:
    with Session.begin() as session:
        league = League(name="Gym Cups")
        session.add(league)
        session.flush()
        league_id = league.id
    first = add_event(name="Open Cup")
    draft = add_event(name="Hidden Cup", published=False)
    koth = add_event(name="Night 1", kind=EventKind.koth, league_id=league_id)

    rows = client.get("/events", headers=auth_headers).json()
    assert [(row["id"], row["phase"]) for row in rows] == [
        (koth, "signups_open"),
        (draft, "draft"),
        (first, "signups_open"),
    ]

    assert [
        row["id"]
        for row in client.get("/events?published=true", headers=auth_headers).json()
    ] == [koth, first]
    assert [row["id"] for row in client.get("/events?kind=koth").json()] == [koth]
    assert [
        row["id"] for row in client.get(f"/events?league_id={league_id}").json()
    ] == [koth]
    assert [row["id"] for row in client.get("/events?limit=1").json()] == [koth]
    assert [
        row["id"] for row in client.get("/events?offset=2", headers=auth_headers).json()
    ] == [first]


def test_the_event_list_hides_a_draft_from_everyone_but_an_admin(
    client: Client,
    auth_headers: dict[str, str],
    member: Callable[..., dict[str, str]],
) -> None:
    """A draft is an admin's own; the filter still asks for one as an admin."""
    live = add_event(name="Open Cup")
    draft = add_event(name="Hidden Cup", published=False)

    assert [row["id"] for row in client.get("/events").json()] == [live]
    assert [row["id"] for row in client.get("/events", headers=member()).json()] == [
        live
    ]
    # The filter holds, and a reader asking for the drafts is answered none
    assert client.get("/events?published=false", headers=member()).json() == []
    assert [
        row["id"]
        for row in client.get("/events?published=false", headers=auth_headers).json()
    ] == [draft]


def test_a_draft_hides_from_its_league_page_and_from_its_own_read(
    client: Client,
    auth_headers: dict[str, str],
    member: Callable[..., dict[str, str]],
) -> None:
    """A draft is out of the league's runs and its id answers not found."""
    with Session.begin() as session:
        league = League(name="Fig Cup", short_name="FIG")
        session.add(league)
        session.flush()
        league_id = league.id
    assert league_id is not None
    live = add_event(name="Fig Cup 6", league_id=league_id)
    draft = add_event(name="Hidden Cup", league_id=league_id, published=False)

    def runs(headers: dict[str, str] | None = None) -> list[int]:
        body = client.get(f"/leagues/{league_id}", headers=headers).json()
        return [event["id"] for event in body["events"]]

    assert runs() == [live]
    assert runs(member()) == [live]
    assert runs(auth_headers) == [draft, live]

    assert client.get(f"/events/{draft}").status_code == 404
    assert client.get(f"/events/{draft}", headers=member()).status_code == 404
    assert client.get(f"/events/{draft}", headers=auth_headers).status_code == 200

    # A draft qualifier is out of its parent's children for the same reason
    set_fields(draft, parent_id=live)
    assert client.get(f"/events/{live}").json()["children"] == []
    body = client.get(f"/events/{live}", headers=auth_headers).json()
    assert [child["id"] for child in body["children"]] == [draft]


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
            "rules_url": None,
            "stream_url": None,
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
        json={
            "short_name": "GC",
            "page_url": "https://cups",
            "rules_url": "https://cups/rules",
            "stream_url": "https://twitch.tv/cups",
        },
        headers=auth_headers,
    )
    assert updated.status_code == 200, updated.text
    assert client.get(f"/leagues/{league_id}").json() == {
        "id": league_id,
        "name": "Gym Cups",
        "short_name": "GC",
        "page_url": "https://cups",
        "rules_url": "https://cups/rules",
        "stream_url": "https://twitch.tv/cups",
        "kind": "custom",
        "entrant_kind": "solo",
        "events": [],
    }


def test_a_new_league_stores_its_rules_page_and_its_stream(
    client: Client, auth_headers: dict[str, str]
) -> None:
    """The two links come in on the create body and read back on the league."""
    created = client.post(
        "/leagues",
        json={
            "name": "Fountain of Manner League",
            "short_name": "FOML",
            "rules_url": "https://foml/rules",
            "stream_url": "https://twitch.tv/foml",
        },
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    assert created.json()["rules_url"] == "https://foml/rules"
    assert created.json()["stream_url"] == "https://twitch.tv/foml"

    body = client.get(f"/leagues/{created.json()['id']}").json()
    assert (body["rules_url"], body["stream_url"]) == (
        "https://foml/rules",
        "https://twitch.tv/foml",
    )


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


def test_an_empty_stage_list_clears_the_stages(
    client: Client, auth_headers: dict[str, str]
) -> None:
    """The default stage is written on create; an empty list later clears them."""
    created = client.post("/events", json={"name": "Spring Cup"}, headers=auth_headers)
    assert created.status_code == 201, created.text
    event_id = created.json()["id"]
    assert len(created.json()["stages"]) == 1

    cleared = client.put(f"/events/{event_id}/stages", json=[], headers=auth_headers)
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["stages"] == []
    assert client.get(f"/events/{event_id}").json()["stages"] == []


def test_an_event_reads_how_many_series_an_entrant_plays_per_round(
    client: Client, auth_headers: dict[str, str]
) -> None:
    """series_per_round is written on the event and read back on its payload."""
    created = client.post(
        "/events",
        json={"name": "FOML Season 4", "series_per_round": 2},
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    assert created.json()["series_per_round"] == 2
    event_id = created.json()["id"]

    assert client.get(f"/events/{event_id}").json()["series_per_round"] == 2
    assert client.get("/events").json()[0]["series_per_round"] == 2


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
    assert phase(client, event, auth_headers) == "draft"
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


def test_an_event_carries_a_parent_a_policy_and_the_entrant_kind_of_its_league(
    client: Client, auth_headers: dict[str, str]
) -> None:
    """A new event copies the entrant kind of its league, and the body may
    name a parent and a signup policy of its own."""
    with Session.begin() as session:
        league = League(name="Gym Teams", entrant_kind=EntrantKind.team)
        session.add(league)
        session.flush()
        league_id = league.id

    main = client.post(
        "/events",
        json={"name": "Team Cup", "kind": "cup", "league_id": league_id},
        headers=auth_headers,
    )
    assert main.status_code == 201, main.text
    assert main.json()["entrant_kind"] == "team"
    assert main.json()["signup_policy"] == "members"
    assert main.json()["parent_id"] is None

    qualifier = client.post(
        "/events",
        json={
            "name": "Team Cup Qualifier",
            "kind": "cup",
            "league_id": league_id,
            "parent_id": main.json()["id"],
            "signup_policy": "anyone",
            "entrant_kind": "solo",
        },
        headers=auth_headers,
    )
    assert qualifier.status_code == 201, qualifier.text
    assert qualifier.json()["parent_id"] == main.json()["id"]
    assert qualifier.json()["signup_policy"] == "anyone"
    # The body names the entrant kind, so the league's is not copied over it
    assert qualifier.json()["entrant_kind"] == "solo"

    # The parent reads its qualifiers, and the league lists them under it
    read = client.get(f"/events/{main.json()['id']}").json()
    assert [child["id"] for child in read["children"]] == [qualifier.json()["id"]]
    league_body = client.get(f"/leagues/{league_id}").json()
    assert [event["id"] for event in league_body["events"]] == [main.json()["id"]]
    assert [child["id"] for child in league_body["events"][0]["children"]] == [
        qualifier.json()["id"]
    ]


def test_an_event_with_no_league_enters_players(
    client: Client, auth_headers: dict[str, str]
) -> None:
    created = client.post("/events", json={"name": "Loose Cup"}, headers=auth_headers)
    assert created.status_code == 201, created.text
    assert created.json()["entrant_kind"] == "solo"


def test_a_stage_reads_its_group_settings_and_its_advance_flag(
    client: Client, auth_headers: dict[str, str]
) -> None:
    """A new stage reads the group settings empty and the advance flag off,
    and the event read echoes what is written on them."""
    created = client.post(
        "/events",
        json={"name": "Group Cup", "stages": [{"name": "Groups"}]},
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    stage = created.json()["stages"][0]
    assert (stage["group_size"], stage["group_advance"], stage["auto_advance"]) == (
        None,
        None,
        False,
    )

    with Session.begin() as session:
        row = session.get(EventStage, stage["id"])
        assert row is not None
        row.sqlmodel_update({"group_size": 4, "group_advance": 2, "auto_advance": True})

    read = client.get(f"/events/{created.json()['id']}").json()["stages"][0]
    assert (read["group_size"], read["group_advance"], read["auto_advance"]) == (
        4,
        2,
        True,
    )


def test_a_team_entrant_names_a_team_and_a_player_entrant_a_user(
    client: Client, seeded: dict[str, Any]
) -> None:
    """One of the two columns is filled, never both and never neither."""
    from sqlalchemy.exc import IntegrityError

    from app.models.team import Team

    event = add_event(name="Team Night")
    with Session.begin() as session:
        league = League(name="Team League", entrant_kind=EntrantKind.team)
        session.add(league)
        session.flush()
        session.get_one(Season, event).league_id = league.id
        team = Team(name="Alpha", league_id=ident(league))
        session.add(team)
        session.flush()
        team_id = ident(team)
        session.add(EventEntrant(event_id=event, team_id=team_id, race=Race.HU))

    with Session.begin() as session:
        rows = session.query(EventEntrant).filter_by(event_id=event).all()
        assert [(row.user_id, row.team_id) for row in rows] == [(None, team_id)]

    # Both sides filled, and neither side filled, are the two the check refuses
    refused = (
        EventEntrant(
            event_id=event,
            user_id=seeded["player_ids"][0],
            team_id=team_id,
            race=Race.HU,
        ),
        EventEntrant(event_id=event, race=Race.HU),
    )
    for row in refused:
        # The commit is the check: the row is refused as it is written
        with pytest.raises(IntegrityError), Session.begin() as session:
            session.add(row)


def test_a_bracket_series_holds_its_feeders_and_no_sides_until_they_are_scored(
    client: Client, seeded: dict[str, Any]
) -> None:
    """A generated series names the two it takes its sides from; the sides
    stay null until those are played."""
    from app.models.series import Series, SeriesFeedersPublic

    with Session.begin() as session:
        played = session.query(Series).order_by(col(Series.id)).first()
        assert played is not None
        final = Series(
            match_id=played.match_id,
            host_player_id=0,
            sequence=2,
            side_size=1,
            pick_rule="drafted",
            result_kind="walkover",
            slot1_from_series_id=played.id,
            slot2_from_series_id=played.id,
            slot2_takes_loser=True,
        )
        session.add(final)
        session.flush()
        assert (final.player1_id, final.player2_id) == (None, None)
        assert SeriesFeedersPublic.from_series(final).to_dict() == {
            "id": final.id,
            "result_kind": "walkover",
            "slot1_from_series_id": played.id,
            "slot1_takes_loser": False,
            "slot2_from_series_id": played.id,
            "slot2_takes_loser": True,
        }
        # Every series that already exists is played and carries no feeder
        assert (played.result_kind, played.sequence, played.side_size) == (
            "played",
            None,
            1,
        )
        assert played.slot1_from_series_id is None
        session.delete(final)


def test_a_fixture_and_a_series_read_the_division_they_are_played_in(
    client: Client, seeded: dict[str, Any]
) -> None:
    from app.models.match import Match
    from app.models.series import Series

    with Session.begin() as session:
        division = EventDivision(
            event_id=seeded["season_id"], position=1, name="Beginners"
        )
        session.add(division)
        session.flush()
        match = session.get(Match, seeded["match_id"])
        assert match is not None
        match.division_id = division.id
        series = session.query(Series).filter_by(match_id=match.id).first()
        assert series is not None
        series.division_id = division.id
        session.flush()
        assert (match.division_id, series.division_id) == (division.id, division.id)
        match.division_id = None
        series.division_id = None


def my_events(client: Client, headers: dict[str, str]) -> dict[int, dict[str, Any]]:
    """The caller's own event rows, keyed by event id."""
    response = client.get("/me/events", headers=headers)
    assert response.status_code == 200, response.text
    return {row["id"]: row for row in response.json()}


def enter(event_id: int, user_id: int) -> int:
    """One entrant row for the player, as a signup writes it."""
    with Session.begin() as session:
        row = EventEntrant(event_id=event_id, user_id=user_id, race=Race.HU)
        session.add(row)
        session.flush()
        return ident(row)


def stamp_checked_in(entrant_id: int) -> None:
    with Session.begin() as session:
        row = session.get(EventEntrant, entrant_id)
        assert row is not None
        row.checked_in_at = NOW


def clear_answer_stamp(event_id: int) -> None:
    """An answer as a row older than the stamp column carries it: no stamp."""
    with Session.begin() as session:
        for row in session.scalars(
            select(DBRoundAvailability).where(
                col(DBRoundAvailability.season_id) == event_id
            )
        ):
            row.answered_at = None


def answer_round(
    client: Client,
    headers: dict[str, str],
    event_id: int,
    playday: int,
    checkin_day: Callable[[str], None],
) -> None:
    """The round shape of the check-in: one round_availability row.

    The suite pins the day the round guard reads, so it moves to the day the
    round these tests date is open on.
    """
    checkin_day(TODAY.isoformat())
    response = client.put(
        "/player-availability",
        json={"season_id": event_id, "playday": playday, "available": True},
        headers=headers,
    )
    assert response.status_code == 200, response.text


def test_the_member_events_walk_the_action_words(
    client: Client,
    seeded: dict[str, Any],
    member: Callable[..., dict[str, str]],
    checkin_day: Callable[[str], None],
) -> None:
    """One cup read as the member who joins it: closed, sign up, withdraw,
    check in and checked in; the running season reads view."""
    headers = member()
    player = seeded["player_ids"][0]
    hidden = add_event(name="Hidden Cup", kind=EventKind.cup, published=False)
    event = add_event(kind=EventKind.cup, signups_open=False, checkin_days=3)

    rows = my_events(client, headers)
    # A draft is an admin's own, so the member read does not carry it
    assert hidden not in rows
    assert rows[event]["action"] == "closed"

    set_fields(event, signups_open=True)
    assert my_events(client, headers)[event]["action"] == "sign_up"

    entrant = enter(event, player)
    row = my_events(client, headers)[event]
    # Nothing to check into yet, so the one action is to take the signup back
    assert (row["action"], row["entrant_id"], row["checkin_shape"]) == (
        "withdraw",
        entrant,
        "event",
    )

    add_round(event, TODAY + timedelta(days=1), TODAY + timedelta(days=2))
    row = my_events(client, headers)[event]
    assert (row["action"], row["checkin_shape"], row["checkin_open"]) == (
        "check_in",
        "round",
        True,
    )
    assert row["next_round"]["number"] == 1

    answer_round(client, headers, event, 1, checkin_day)
    row = my_events(client, headers)[event]
    assert (row["action"], row["checked_in_at"] is not None) == ("checked_in", True)

    # A season with a series under way reads view, whoever the caller is
    set_fields(seeded["season_id"], end_date=TODAY + timedelta(days=7))
    running = my_events(client, headers)[seeded["season_id"]]
    assert (running["phase"], running["action"]) == ("running", "view")


def test_the_event_check_in_refuses_when_the_event_checks_in_per_round(
    client: Client,
    seeded: dict[str, Any],
    member: Callable[..., dict[str, str]],
) -> None:
    """The event shape stamps the entrant; a dated round takes over from it."""
    headers = member()
    entrant = enter(
        add_event(kind=EventKind.cup, checkin_days=3), seeded["player_ids"][0]
    )
    with Session.begin() as session:
        row = session.get(EventEntrant, entrant)
        assert row is not None
        event = row.event_id

    stamped = client.post(
        f"/events/{event}/entrants/{entrant}/checkin", headers=headers
    )
    assert stamped.status_code == 200, stamped.text
    assert stamped.json()["checked_in_at"] is not None

    add_round(event, TODAY + timedelta(days=1), TODAY + timedelta(days=2))
    refused = client.post(
        f"/events/{event}/entrants/{entrant}/checkin", headers=headers
    )
    assert refused.status_code == 400
    assert refused.json() == {
        "error": "This event checks in per round. Answer the round instead."
    }


def test_a_cup_with_rounds_takes_the_round_check_in(
    client: Client,
    seeded: dict[str, Any],
    member: Callable[..., dict[str, str]],
    auth_headers: dict[str, str],
) -> None:
    """The round shape is one route for every kind: a cup's round-robin rounds
    answer PUT /player-availability the way a GNL season's do."""
    from app.models.enums import StageFormat
    from tests.test_stage_engine import cup, generate

    event, (stage,) = cup(4, StageFormat.round_robin)
    assert generate(client, auth_headers, event, stage)["rounds"] == 3

    response = client.put(
        "/player-availability",
        json={"season_id": event, "playday": 1, "available": False},
        headers=member(),
    )
    assert response.status_code == 200, response.text
    assert [(row["playday"], row["available"]) for row in response.json()] == [
        (1, False)
    ]


def test_the_round_answer_is_the_check_in_of_a_dated_round(
    client: Client,
    seeded: dict[str, Any],
    member: Callable[..., dict[str, str]],
    checkin_day: Callable[[str], None],
) -> None:
    """A cup with a dated round checks in through PUT /player-availability, so
    the member home reads that answer and dates it from the answer's own stamp.

    A row written before the stamp column falls back to the window's opening.
    """
    headers = member()
    event = add_event(kind=EventKind.cup, checkin_days=3)
    enter(event, seeded["player_ids"][0])
    add_round(event, TODAY + timedelta(days=1), TODAY + timedelta(days=2))

    row = my_events(client, headers)[event]
    assert (row["checkin_shape"], row["action"], row["checked_in_at"]) == (
        "round",
        "check_in",
        None,
    )

    answer_round(client, headers, event, 1, checkin_day)
    row = my_events(client, headers)[event]
    assert row["action"] == "checked_in"
    assert row["checked_in_at"].startswith(str(TODAY))

    clear_answer_stamp(event)
    row = my_events(client, headers)[event]
    assert row["checked_in_at"] == f"{TODAY - timedelta(days=2)}T00:00:00Z"


def test_the_entrant_stamp_is_no_check_in_of_a_dated_round(
    client: Client,
    seeded: dict[str, Any],
    member: Callable[..., dict[str, str]],
) -> None:
    """The event route refuses a round-shaped event, and a stamp left on the
    entrant row from before the round was dated does not read as checked in."""
    headers = member()
    event = add_event(kind=EventKind.cup, checkin_days=3)
    entrant = enter(event, seeded["player_ids"][0])
    add_round(event, TODAY + timedelta(days=1), TODAY + timedelta(days=2))
    stamp_checked_in(entrant)

    refused = client.post(
        f"/events/{event}/entrants/{entrant}/checkin", headers=headers
    )
    assert refused.status_code == 400, refused.text

    row = my_events(client, headers)[event]
    assert (row["checkin_shape"], row["action"], row["checked_in_at"]) == (
        "round",
        "check_in",
        None,
    )


def signup_only(client: Client, headers: dict[str, str], **fields: Any) -> int:  # noqa: ANN401
    """A coaching session: kind signup, no stage, created through the route."""
    response = client.post(
        "/events",
        json={"name": "Coaching Night", "kind": "signup", "stages": [], **fields},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    assert response.json()["stages"] == []
    return int(response.json()["id"])


def test_an_explicit_empty_stage_list_writes_no_stage(
    client: Client, auth_headers: dict[str, str]
) -> None:
    """A body that sends an empty stage list plays no stage, where a body that
    leaves the field out plays one default stage. The stages route still runs."""
    event = signup_only(client, auth_headers)
    assert client.get(f"/events/{event}").json()["stages"] == []
    added = client.put(
        f"/events/{event}/stages",
        json=[{"format": "round_robin", "best_of": 3}],
        headers=auth_headers,
    )
    assert added.status_code == 200, added.text
    assert len(added.json()["stages"]) == 1

    cleared = client.put(f"/events/{event}/stages", json=[], headers=auth_headers)
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["stages"] == []


def test_a_coaching_session_takes_eight_signups_and_refuses_the_ninth(
    client: Client,
    seeded: dict[str, Any],
    auth_headers: dict[str, str],
    member: Callable[..., dict[str, str]],
) -> None:
    """An event with no stage still caps its entrants and checks in as itself."""
    headers = member()
    event = signup_only(client, auth_headers, entrant_cap=8)

    enter(event, seeded["player_ids"][0])
    for index in range(2, 9):
        added = client.post(
            f"/events/{event}/entrants/admin",
            json={"race": "HU", "battle_tag": f"Coach{index}#{index}000"},
            headers=auth_headers,
        )
        assert added.status_code == 201, added.text

    full = client.post(
        f"/events/{event}/entrants/admin",
        json={"race": "HU", "battle_tag": "Coach9#9000"},
        headers=auth_headers,
    )
    assert full.status_code == 400
    assert full.json() == {"error": "The event is full at 8 entrants"}

    entrants = client.get(f"/events/{event}/entrants")
    assert entrants.status_code == 200, entrants.text
    assert len(entrants.json()) == 8

    # No stage means no round, so the check-in is the event itself
    row = my_events(client, headers)[event]
    assert (row["checkin_shape"], row["availability_hint"]) == ("event", None)


def block_all_day(user_id: int) -> None:
    """Two repeating blocks that together cover every local day, and a zone."""
    from datetime import time

    from app.models.user_block import UserBlock

    with Session.begin() as session:
        user = session.get(User, user_id)
        assert user is not None
        user.timezone = "Europe/Berlin"
        session.add_all(
            UserBlock(
                user_id=user_id,
                weekdays=127,
                start_local=start,
                end_local=end,
            )
            for start, end in ((time(), time(12)), (time(12), time()))
        )


def test_the_member_row_hints_that_the_blocks_cover_the_next_round(
    client: Client,
    seeded: dict[str, Any],
    member: Callable[..., dict[str, str]],
) -> None:
    """Blocks that cover the whole round window read as a hint, and the
    player's own answer wins over them: blocks inform, they never constrain."""
    headers = member()
    player = seeded["player_ids"][0]
    event = add_event(kind=EventKind.cup, checkin_days=3)
    add_round(event, TODAY, TODAY)
    enter(event, player)

    assert my_events(client, headers)[event]["availability_hint"] == "open"

    block_all_day(player)
    assert my_events(client, headers)[event]["availability_hint"] == "blocked_by_blocks"

    with Session.begin() as session:
        session.add(
            DBRoundAvailability(
                user_id=player,
                season_id=event,
                playday=1,
                available=False,
                set_by_user_id=player,
            )
        )
    row = my_events(client, headers)[event]
    assert (row["availability_hint"], row["action"]) == ("answered_no", "checked_in")
