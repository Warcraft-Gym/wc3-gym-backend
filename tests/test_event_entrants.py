"""Signing up to an event, withdrawing, checking in and the eligibility warnings.

A warning never refuses a signup: the entrant row carries it and an admin
decides. The GNL season keeps its own signup route, so a gnl-kind event
refuses here and names it.
"""

from collections.abc import Callable
from typing import Any

from httpx2 import Client, Response

from app.core.db import Session
from app.models.enums import EventKind, Race, SignupPolicy
from app.models.relationships import DBTeamSeasonCaptain
from app.models.w3c_stats import W3CStats
from tests.test_events import add_event, set_fields

type Member = Callable[..., dict[str, str]]


def entrants(client: Client, event_id: int) -> list[dict[str, Any]]:
    response = client.get(f"/events/{event_id}/entrants")
    assert response.status_code == 200, response.text
    return response.json()


def sign_up(
    client: Client,
    event_id: int,
    headers: dict[str, str] | None = None,
    **body: str | int,
) -> Response:
    return client.post(
        f"/events/{event_id}/entrants", json={"race": "HU"} | body, headers=headers
    )


def test_a_member_signs_up_checks_in_and_withdraws(
    client: Client, seeded: dict[str, Any], member: Member
) -> None:
    """The row carries the player through UserPublic and keeps its stamps."""
    event = add_event(kind=EventKind.cup)
    headers = member("1")

    created = sign_up(client, event, headers)
    assert created.status_code == 201, created.text
    assert created.json()["user"]["battleTag"] == "P1#1111"
    assert created.json()["race"] == "HU"
    assert created.json()["channel"] == "web"
    assert created.json()["warnings"] == []
    entrant_id = created.json()["id"]

    checked = client.post(
        f"/events/{event}/entrants/{entrant_id}/checkin", headers=headers
    )
    assert checked.status_code == 200, checked.text
    assert checked.json()["checked_in_at"] is not None

    assert (
        client.delete(f"/events/{event}/entrants/me", headers=headers).status_code
        == 204
    )
    row = entrants(client, event)[0]
    assert row["withdrawn_at"] is not None
    assert client.get(f"/events/{event}").json()["entrant_count"] == 0


def test_a_withdrawn_player_signs_up_again_on_the_same_row(
    client: Client, seeded: dict[str, Any], member: Member
) -> None:
    """One entrant is one row, so a return signup reopens the one left behind."""
    event = add_event(kind=EventKind.cup)
    headers = member("1")
    assert sign_up(client, event, headers).status_code == 201
    client.delete(f"/events/{event}/entrants/me", headers=headers)

    again = sign_up(client, event, headers, race="OC")

    assert again.status_code == 201, again.text
    assert again.json()["withdrawn_at"] is None
    assert again.json()["race"] == "OC"
    assert len(entrants(client, event)) == 1


def test_an_anyone_event_takes_a_battle_tag_with_no_session(client: Client) -> None:
    """A KOTH-style signup: the battle tag finds or makes the player row."""
    event = add_event(kind=EventKind.koth, signup_policy=SignupPolicy.anyone)

    created = sign_up(client, event, battle_tag="Newcomer#9999", race="NE")

    assert created.status_code == 201, created.text
    assert created.json()["user"]["battleTag"] == "Newcomer#9999"
    assert created.json()["user"]["name"] == "Newcomer"
    assert client.get("/users/Newcomer%239999").status_code == 200
    # The same tag finds the row it made rather than a second one
    assert sign_up(client, event, battle_tag="newcomer#9999").status_code == 400


def test_a_members_event_refuses_a_caller_with_no_session(client: Client) -> None:
    event = add_event(kind=EventKind.cup)

    assert sign_up(client, event).status_code == 401


def test_a_captain_enters_the_team_and_another_member_may_not(
    client: Client, seeded: dict[str, Any], member: Member
) -> None:
    event = add_event(kind=EventKind.cup)
    with Session.begin() as session:
        session.add(
            DBTeamSeasonCaptain(
                user_id=seeded["player_ids"][0],
                team_id=seeded["team_a_id"],
                season_id=seeded["season_id"],
            )
        )

    created = sign_up(client, event, member("1"), team_id=seeded["team_a_id"])

    assert created.status_code == 201, created.text
    assert created.json()["team"]["name"] == "Alpha"
    assert created.json()["user"] is None
    refused = sign_up(client, event, member("2"), team_id=seeded["team_b_id"])
    assert refused.status_code == 403
    assert refused.json() == {"error": "Only a captain of the team enters it"}


def test_the_signup_refuses_when_it_is_closed_full_or_already_taken(
    client: Client, seeded: dict[str, Any], member: Member
) -> None:
    """No waiting list is built: a full event refuses and says so."""
    event = add_event(kind=EventKind.cup, entrant_cap=1)
    assert sign_up(client, event, member("1")).status_code == 201

    full = sign_up(client, event, member("2"))
    assert full.status_code == 400
    assert full.json() == {"error": "The event is full at 1 entrants"}
    twice = sign_up(client, event, member("1"))
    assert twice.json() == {"error": "This entrant is already signed up"}

    set_fields(event, signups_open=False)
    closed = sign_up(client, event, member("3"))
    assert closed.status_code == 400
    assert closed.json() == {"error": "Signups are closed for this event"}


def test_the_entrant_row_warns_on_games_rating_and_a_ban(
    client: Client,
    seeded: dict[str, Any],
    member: Member,
    auth_headers: dict[str, str],
) -> None:
    """Three warnings, and none of them refuses the signup."""
    event = add_event(kind=EventKind.cup, min_games=50, mmr_max=1800)
    player = seeded["player_ids"][0]
    with Session.begin() as session:
        session.add(
            W3CStats(user_id=player, race=Race.HU, wc3_season=22, games=10, mmr=2000)
        )
    assert client.put(f"/users/{player}/ban", headers=auth_headers).status_code == 204

    created = sign_up(client, event, member("1"))

    assert created.status_code == 201, created.text
    assert created.json()["mmr"] == 2000
    assert created.json()["warnings"] == [
        "under_min_games",
        "over_mmr_max",
        "banned",
    ]
    assert (
        client.delete(f"/users/{player}/ban", headers=auth_headers).status_code == 204
    )
    assert entrants(client, event)[0]["warnings"] == [
        "under_min_games",
        "over_mmr_max",
    ]
    assert client.put("/users/404/ban", headers=auth_headers).status_code == 404
    assert client.put(f"/users/{player}/ban").status_code == 401


def test_the_rating_walks_back_to_the_newest_season_the_race_played(
    client: Client, seeded: dict[str, Any], member: Member
) -> None:
    """A season the player sat out carries no rating, so the read walks back.

    Three seasons back and no further: a rating older than that is not the
    player's current one.
    """
    event = add_event(kind=EventKind.cup)
    player = seeded["player_ids"][0]
    with Session.begin() as session:
        session.add_all(
            [
                W3CStats(
                    user_id=player, race=Race.HU, wc3_season=20, games=80, mmr=1700
                ),
                W3CStats(
                    user_id=player, race=Race.NE, wc3_season=22, games=40, mmr=1500
                ),
            ]
        )

    created = sign_up(client, event, member("1"))

    assert created.status_code == 201, created.text
    assert created.json()["mmr"] == 1700

    with Session.begin() as session:
        session.add(
            W3CStats(user_id=player, race=Race.NE, wc3_season=23, games=40, mmr=1500)
        )
    # Season 20 now sits four seasons behind the season the app is on
    assert entrants(client, event)[0]["mmr"] is None


def test_a_rating_older_than_the_window_is_not_read_at_all(
    client: Client, seeded: dict[str, Any], member: Member
) -> None:
    """The window hangs on the season the app is on, not on the player's own rows.

    A player who last played eight seasons ago carries no current rating, so
    the entrant row reads none of it.
    """
    event = add_event(kind=EventKind.cup)
    lapsed, current = seeded["player_ids"][0], seeded["player_ids"][1]
    with Session.begin() as session:
        session.add_all(
            [
                W3CStats(
                    user_id=lapsed, race=Race.HU, wc3_season=15, games=80, mmr=1900
                ),
                W3CStats(
                    user_id=current, race=Race.HU, wc3_season=23, games=80, mmr=1500
                ),
            ]
        )

    assert sign_up(client, event, member("1")).status_code == 201
    assert sign_up(client, event, member("2")).status_code == 201

    rows = {row["user"]["battleTag"]: row["mmr"] for row in entrants(client, event)}
    assert rows == {"P1#1111": None, "P2#2222": 1500}


def test_a_gnl_event_sends_the_signup_to_its_season_page(
    client: Client, seeded: dict[str, Any], member: Member
) -> None:
    """GNL entrants stay on the season signup table this wave."""
    event = add_event(kind=EventKind.gnl)

    refused = sign_up(client, event, member("1"))

    assert refused.status_code == 400
    assert refused.json() == {
        "error": "A GNL season takes its signups on its season page"
    }


def test_an_admin_enters_and_removes_any_player(
    client: Client, seeded: dict[str, Any], auth_headers: dict[str, str]
) -> None:
    """An admin enters after signups close, and the removal deletes the row."""
    event = add_event(kind=EventKind.cup, signups_open=False)
    player = seeded["player_ids"][1]

    created = client.post(
        f"/events/{event}/entrants/admin",
        json={"user_id": player, "race": "OC", "channel": "bot"},
        headers=auth_headers,
    )

    assert created.status_code == 201, created.text
    assert created.json()["user"]["battleTag"] == "P2#2222"
    assert created.json()["channel"] == "bot"
    entrant_id = created.json()["id"]
    checked = client.post(
        f"/events/{event}/entrants/{entrant_id}/checkin", headers=auth_headers
    )
    assert checked.status_code == 200, checked.text
    assert checked.json()["checked_in_at"] is not None

    nameless = client.post(
        f"/events/{event}/entrants/admin", json={"race": "HU"}, headers=auth_headers
    )
    assert nameless.status_code == 400
    assert nameless.json() == {"error": "Name a user_id, a battle_tag or a team_id"}
    assert client.delete(f"/events/{event}/entrants/{entrant_id}").status_code == 401
    removed = client.delete(
        f"/events/{event}/entrants/{entrant_id}", headers=auth_headers
    )
    assert removed.status_code == 204
    assert entrants(client, event) == []


def test_a_member_checks_in_nobody_else_and_withdraws_nothing_twice(
    client: Client, seeded: dict[str, Any], member: Member, auth_headers: dict[str, str]
) -> None:
    event = add_event(kind=EventKind.cup)
    created = client.post(
        f"/events/{event}/entrants/admin",
        json={"user_id": seeded["player_ids"][0], "race": "HU"},
        headers=auth_headers,
    )
    entrant_id = created.json()["id"]

    refused = client.post(
        f"/events/{event}/entrants/{entrant_id}/checkin", headers=member("2")
    )

    assert refused.status_code == 403
    assert refused.json() == {"error": "Check in your own signup"}
    gone = client.delete(f"/events/{event}/entrants/me", headers=member("2"))
    assert gone.status_code == 404
    assert gone.json() == {"error": "No signup to withdraw"}
    unknown = client.post(f"/events/{event}/entrants/404/checkin", headers=auth_headers)
    assert unknown.json() == {"error": "Entrant not found by id: 404"}


def test_a_team_enters_on_no_race_and_carries_its_note(
    client: Client, seeded: dict[str, Any], member: Member
) -> None:
    """A team fields the races of its roster, so its row names none of them."""
    event = add_event(kind=EventKind.cup)
    with Session.begin() as session:
        session.add(
            DBTeamSeasonCaptain(
                user_id=seeded["player_ids"][0],
                team_id=seeded["team_a_id"],
                season_id=seeded["season_id"],
            )
        )

    created = client.post(
        f"/events/{event}/entrants",
        json={"team_id": seeded["team_a_id"], "note": "Late game macro"},
        headers=member("1"),
    )

    assert created.status_code == 201, created.text
    assert created.json()["race"] is None
    assert created.json()["note"] == "Late game macro"
    assert entrants(client, event)[0]["note"] == "Late game macro"


def test_a_player_names_the_race_they_sign_up_on(
    client: Client, seeded: dict[str, Any], member: Member
) -> None:
    """One player plays one race, so a player row without one is refused."""
    event = add_event(kind=EventKind.cup)

    refused = client.post(
        f"/events/{event}/entrants",
        json={"note": "Creep routes"},
        headers=member("1"),
    )

    assert refused.status_code == 400, refused.text
    assert refused.json() == {"error": "Name the race you sign up on"}
    entered = sign_up(client, event, member("1"), note="Creep routes")
    assert entered.status_code == 201, entered.text
    assert (entered.json()["race"], entered.json()["note"]) == ("HU", "Creep routes")
