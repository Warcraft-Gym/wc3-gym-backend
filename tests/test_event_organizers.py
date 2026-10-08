"""Event organizers: a member an admin granted creates small events and runs
the ones it holds a row of; a GNL season and a KOTH night stay the admins'.

The minimum an event is played with, and calling an event off, sit here too:
both are steps an organizer takes on the evening of a cup.
"""

from collections.abc import Callable
from typing import Any

from httpx2 import Client
from sqlmodel import select

from app.core.db import Session
from app.models.enums import LeagueKind
from app.models.league import League
from app.models.season import Season
from app.models.series import Series
from app.services import organizers
from tests.test_stage_engine import cup, players

Headers = dict[str, str]
Member = Callable[..., Headers]

CUP = {
    "name": "Friday Night Cup",
    "kind": "cup",
    "stages": [{"format": "single_elimination", "best_of": 3}],
}


def grant(client: Client, admin: Headers, discord_id: str) -> None:
    response = client.post(
        "/organizers", json={"discord_id": discord_id}, headers=admin
    )
    assert response.status_code == 201, response.text


def create(client: Client, headers: Headers, **fields: Any) -> dict[str, Any]:  # noqa: ANN401
    response = client.post("/events", json=CUP | fields, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def enter(client: Client, headers: Headers, event: int, user_ids: list[int]) -> None:
    for user_id in user_ids:
        response = client.post(
            f"/events/{event}/entrants/admin",
            json={"user_id": user_id, "race": "HU"},
            headers=headers,
        )
        assert response.status_code == 201, response.text


def draw(client: Client, headers: Headers, event: dict[str, Any]) -> Any:  # noqa: ANN401
    stage = event["stages"][0]["id"]
    seeds = client.put(
        f"/events/{event['id']}/stages/{stage}/seeds",
        json={"source": "mmr"},
        headers=headers,
    )
    assert seeds.status_code == 200, seeds.text
    return client.post(
        f"/events/{event['id']}/stages/{stage}/generate", headers=headers
    )


def custom_league() -> int:
    with Session.begin() as session:
        league = League(name="Gym Cups", short_name="CUP", kind=LeagueKind.custom)
        session.add(league)
        session.flush()
        assert league.id is not None
        return league.id


def gnl_league() -> int:
    with Session.begin() as session:
        league = League(name="Newbie League", short_name="NL", kind=LeagueKind.gnl)
        session.add(league)
        session.flush()
        assert league.id is not None
        return league.id


def test_an_organizer_creates_a_cup_and_runs_it_to_the_end(
    client: Client, auth_headers: Headers, member: Member
) -> None:
    grant(client, auth_headers, "50")
    headers = member("50")
    assert client.get("/me", headers=headers).json()["organizer"] is True

    event = create(client, headers, league_id=custom_league())
    assert [
        row["discord_id"]
        for row in client.get(f"/events/{event['id']}/organizers").json()
    ] == ["50"]

    enter(client, headers, event["id"], players(4))
    assert draw(client, headers, event).status_code == 200

    series = client.get(
        f"/events/{event['id']}/stages/{event['stages'][0]['id']}/series"
    ).json()
    first = series["series"][0]["id"]
    walkover = client.put(
        f"/series/{first}/result-kind",
        json={"result_kind": "walkover", "winner": 1},
        headers=headers,
    )
    assert walkover.status_code == 200, walkover.text

    finished = client.post(f"/events/{event['id']}/finish", headers=headers)
    assert finished.status_code == 200, finished.text


def test_an_organizer_reports_a_result_without_a_player_row(
    client: Client, auth_headers: Headers, member: Member
) -> None:
    """The organizer acts for either side, as an admin does, and needs no
    player row of its own to do it."""
    grant(client, auth_headers, "52")
    headers = member("52")
    event = create(client, headers)
    enter(client, headers, event["id"], players(2))
    assert draw(client, headers, event).status_code == 200
    with Session.begin() as session:
        series = session.scalars(select(Series)).one()
        series_id = series.id

    report = client.put(
        f"/player-series/{series_id}",
        json={"player1_score": 2, "player2_score": 0},
        headers=headers,
    )
    assert report.status_code == 200, report.text
    stranger = client.put(
        f"/player-series/{series_id}",
        json={"player1_score": 0, "player2_score": 2},
        headers=member("53"),
    )
    assert stranger.status_code in (403, 404)


def test_an_organizer_runs_only_the_events_it_holds_a_row_of(
    client: Client, auth_headers: Headers, member: Member, seeded: dict[str, Any]
) -> None:
    grant(client, auth_headers, "50")
    grant(client, auth_headers, "51")
    event = create(client, member("50"))
    other = member("51")

    assert (
        client.put(
            f"/events/{event['id']}", json={"name": "Taken"}, headers=other
        ).status_code
        == 403
    )
    assert (
        client.post(f"/events/{event['id']}/finish", headers=other).status_code == 403
    )
    # A GNL season names no organizer
    season = seeded["season_id"]
    assert (
        client.put(
            f"/events/{season}", json={"name": "Taken"}, headers=other
        ).status_code
        == 403
    )
    assert client.delete(f"/events/{season}", headers=other).status_code == 403
    # The Discord card stays an admin's to post
    assert (
        client.post(
            f"/events/{event['id']}/discord-post",
            json={"channel_id": "1"},
            headers=member("50"),
        ).status_code
        == 403
    )


def test_an_organizer_stays_inside_small_events(
    client: Client, auth_headers: Headers, member: Member
) -> None:
    grant(client, auth_headers, "50")
    headers = member("50")
    refused = [
        CUP | {"kind": "gnl"},
        CUP | {"kind": "koth"},
        CUP | {"league_id": gnl_league()},
        CUP | {"discordRole": "77"},
        CUP | {"stages": [{"format": "koth"}]},
    ]
    for body in refused:
        assert client.post("/events", json=body, headers=headers).status_code == 403

    event = create(client, headers)
    assert (
        client.put(
            f"/events/{event['id']}", json={"kind": "koth"}, headers=headers
        ).status_code
        == 403
    )
    assert (
        client.put(
            f"/events/{event['id']}/stages", json=[{"format": "gnl"}], headers=headers
        ).status_code
        == 403
    )
    # An admin writes any of them
    assert (
        client.post(
            "/events",
            json=CUP | {"name": "Sign-up list", "kind": "signup", "stages": []},
            headers=auth_headers,
        ).status_code
        == 201
    )


def test_a_member_without_a_grant_creates_nothing(
    client: Client, member: Member
) -> None:
    headers = member("60")
    assert client.get("/me", headers=headers).json()["organizer"] is False
    assert client.post("/events", json=CUP, headers=headers).status_code == 403


def test_a_request_waits_for_an_admin_and_an_approval_grants_it(
    client: Client, auth_headers: Headers, member: Member
) -> None:
    headers = member("70")
    sent = client.post(
        "/organizers/requests", json={"note": "A weekly 1v1 cup"}, headers=headers
    )
    assert sent.status_code == 204, sent.text
    me = client.get("/me", headers=headers).json()
    assert (me["organizer"], me["organizer_request"]) == (False, "pending")

    waiting = client.get("/organizers/requests", headers=auth_headers).json()
    assert [(row["discord_id"], row["name"], row["note"]) for row in waiting] == [
        ("70", "p70", "A weekly 1v1 cup")
    ]
    assert client.get("/organizers/requests", headers=headers).status_code == 403

    approved = client.post("/organizers/requests/70/approve", headers=auth_headers)
    assert approved.status_code == 201, approved.text
    me = client.get("/me", headers=headers).json()
    assert (me["organizer"], me["organizer_request"]) == (True, None)
    assert client.get("/organizers/requests", headers=auth_headers).json() == []
    assert [
        row["name"] for row in client.get("/organizers", headers=auth_headers).json()
    ] == ["p70"]
    # An organizer asks for nothing more
    assert (
        client.post("/organizers/requests", json={}, headers=headers).status_code == 400
    )


def test_a_declined_request_grants_nothing(
    client: Client, auth_headers: Headers, member: Member
) -> None:
    headers = member("71")
    client.post("/organizers/requests", json={}, headers=headers)
    assert (
        client.post("/organizers/requests/71/decline", headers=auth_headers).status_code
        == 204
    )
    me = client.get("/me", headers=headers).json()
    assert (me["organizer"], me["organizer_request"]) == (False, None)


def test_a_co_organizer_runs_the_event_and_a_revoke_keeps_the_rows(
    client: Client, auth_headers: Headers, member: Member
) -> None:
    grant(client, auth_headers, "50")
    creator = member("50")
    event = create(client, creator)
    added = client.post(
        f"/events/{event['id']}/organizers",
        json={"discord_id": "80", "name": "Quill"},
        headers=creator,
    )
    assert added.status_code == 201, added.text
    co = member("80")
    assert (
        client.put(
            f"/events/{event['id']}", json={"name": "Duo Cup"}, headers=co
        ).status_code
        == 200
    )
    # A co-organizer holds no grant, so it creates nothing of its own
    assert client.post("/events", json=CUP, headers=co).status_code == 403

    assert client.delete("/organizers/50", headers=auth_headers).status_code == 204
    assert client.post("/events", json=CUP, headers=creator).status_code == 403
    assert (
        client.put(
            f"/events/{event['id']}", json={"name": "Still mine"}, headers=creator
        ).status_code
        == 200
    )

    assert (
        client.delete(
            f"/events/{event['id']}/organizers/80", headers=creator
        ).status_code
        == 204
    )
    assert (
        client.put(
            f"/events/{event['id']}", json={"name": "Gone"}, headers=co
        ).status_code
        == 403
    )


def test_a_draft_reads_for_its_organizers_only(
    client: Client, auth_headers: Headers, member: Member
) -> None:
    grant(client, auth_headers, "50")
    headers = member("50")
    event = create(client, headers, published=False)
    assert client.get(f"/events/{event['id']}", headers=headers).status_code == 200
    assert client.get(f"/events/{event['id']}", headers=member("90")).status_code == 404
    assert client.get(f"/events/{event['id']}").status_code == 404
    mine = client.get("/me/organized-events", headers=headers).json()
    assert [row["id"] for row in mine] == [event["id"]]
    assert client.get("/me/organized-events", headers=member("90")).json() == []


def test_a_grant_counts_only_for_a_member_acting_as_itself() -> None:
    """A guest or an admin seen as a lower role holds no organizer rights,
    even where a grant names its account."""
    organizers.grant("95", "admin")
    member = {"sub": "95", "role": "member"}
    assert organizers.standing(member) == (True, False)
    assert organizers.standing({"sub": "95", "role": "guest"}) == (False, False)
    viewed = {"sub": "95", "role": "member", "actual_role": "admin"}
    assert organizers.standing(viewed) == (False, False)


def test_the_draw_holds_the_event_to_its_minimum(
    client: Client, auth_headers: Headers
) -> None:
    event, stages = cup(3)
    with Session.begin() as session:
        row = session.get(Season, event)
        assert row is not None
        row.entrant_min = 4
    refused = client.post(
        f"/events/{event}/stages/{stages[0]}/generate", headers=auth_headers
    )
    assert refused.status_code == 400
    assert "at least 4" in refused.json()["error"]

    client.put(f"/events/{event}", json={"entrant_min": 3}, headers=auth_headers)
    drawn = client.post(
        f"/events/{event}/stages/{stages[0]}/generate", headers=auth_headers
    )
    assert drawn.status_code == 200, drawn.text


def test_a_cancel_closes_without_places_and_a_reopen_takes_it_back(
    client: Client, auth_headers: Headers, member: Member
) -> None:
    grant(client, auth_headers, "50")
    headers = member("50")
    event = create(client, headers, signups_open=True)

    cancelled = client.post(f"/events/{event['id']}/cancel", headers=headers)
    assert cancelled.status_code == 200, cancelled.text
    body = cancelled.json()
    assert body["cancelled_at"] is not None
    assert (body["phase"], body["signups_open"]) == ("finished", False)
    assert (
        client.post(f"/events/{event['id']}/finish", headers=headers).status_code == 400
    )

    reopened = client.post(f"/events/{event['id']}/reopen", headers=headers)
    assert reopened.status_code == 200, reopened.text
    assert reopened.json()["cancelled_at"] is None
    assert reopened.json()["closed_at"] is None
