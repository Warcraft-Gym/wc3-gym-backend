"""Event organizers: a member an admin granted creates small events and runs
the ones it holds a row of; a GNL season and a KOTH night stay the admins'.

The minimum an event is played with, and calling an event off, sit here too:
both are steps an organizer takes on the evening of a cup. So does deleting
one, which an organizer does to its own events and an admin to any.
"""

import warnings
from collections.abc import Callable
from typing import Any

from fastapi import FastAPI
from fastapi.openapi.utils import get_openapi
from httpx2 import Client
from sqlmodel import col, select

from app.core.db import Session
from app.models.cup_series import CupSeries
from app.models.cup_settings import CupSettings
from app.models.discord_post import DiscordPost
from app.models.enums import LeagueKind
from app.models.event_award import EventAward
from app.models.event_entrant import EventEntrant
from app.models.league import League
from app.models.organizer import EventOrganizer
from app.models.season import Season
from app.models.user import User
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
    # a cup draws its checked-in players; the draw tests run with check-in off
    body = CUP | {"checkin_enabled": False} | fields
    response = client.post("/events", json=body, headers=headers)
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
    listed = client.get(f"/events/{event['id']}/organizers", headers=headers)
    assert [row["discord_id"] for row in listed.json()] == ["50"]
    # The event page names its organizers to every reader, a guest and a member alike
    for reader in ({}, member("51")):
        read = client.get(f"/events/{event['id']}/organizers", headers=reader)
        assert read.status_code == 200, read.text
        assert [row["discord_id"] for row in read.json()] == ["50"]

    enter(client, headers, event["id"], players(4))
    assert draw(client, headers, event).status_code == 200

    series = client.get(
        f"/events/{event['id']}/stages/{event['stages'][0]['id']}/series"
    ).json()
    first = series["series"][0]["id"]
    walkover = client.put(
        f"/cup-series/{first}/result-kind",
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
        series = session.scalars(select(CupSeries)).one()
        series_id = series.id

    stranger = client.put(
        f"/cup-series/{series_id}/report",
        json={"player1_score": 0, "player2_score": 2},
        headers=member("53"),
    )
    assert stranger.status_code == 403, stranger.text
    report = client.put(
        f"/cup-series/{series_id}/report",
        json={"player1_score": 2, "player2_score": 0},
        headers=headers,
    )
    assert report.status_code == 200, report.text


def test_an_organizer_edits_and_clears_a_result_of_its_own_cup_only(
    client: Client, auth_headers: Headers, member: Member, seeded: dict[str, Any]
) -> None:
    """The run page edits a result through PUT /cup-series and the report
    dialog clears one through DELETE /cup-series/{id}/result: a cup's organizer
    does both as an admin does, a stranger does neither, and a GNL series keeps
    its captains' rules."""
    grant(client, auth_headers, "54")
    headers = member("54")
    event = create(client, headers, name="Result Edit Cup")
    enter(client, headers, event["id"], players(2))
    assert draw(client, headers, event).status_code == 200
    [row] = client.get(
        f"/events/{event['id']}/stages/{event['stages'][0]['id']}/series"
    ).json()["series"]
    series_id = row["id"]

    scored = client.put(
        f"/cup-series/{series_id}",
        json={"player1_score": 2, "player2_score": 0},
        headers=headers,
    )
    assert scored.status_code == 200, scored.text
    turned = client.put(
        f"/cup-series/{series_id}?force=true",
        json={"player1_score": 0, "player2_score": 2},
        headers=headers,
    )
    assert turned.status_code == 200, turned.text
    assert (turned.json()["player1_score"], turned.json()["player2_score"]) == (0, 2)

    stranger = member("55")
    refused = client.put(
        f"/cup-series/{series_id}",
        json={"player1_score": 2, "player2_score": 0},
        headers=stranger,
    )
    assert refused.status_code == 403, refused.text
    assert (
        client.delete(f"/cup-series/{series_id}/result", headers=stranger).status_code
        == 403
    )

    cleared = client.delete(f"/cup-series/{series_id}/result", headers=headers)
    assert cleared.status_code == 200, cleared.text
    assert cleared.json()["player1_score"] is None

    gnl = seeded["series_open_id"]
    assert (
        client.put(
            f"/series/{gnl}",
            json={"player1_score": 2, "player2_score": 0},
            headers=headers,
        ).status_code
        == 403
    )
    assert client.delete(f"/series/{gnl}/result", headers=headers).status_code == 403


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


def test_an_organizer_deletes_its_own_cup_with_everything_under_it(
    client: Client, auth_headers: Headers, member: Member
) -> None:
    """A drawn, played and finished cup goes whole, the rows of its
    announcements too, while a post of another kind stays. Another organizer
    deletes nothing of it."""
    grant(client, auth_headers, "50")
    grant(client, auth_headers, "51")
    headers = member("50")
    event = create(client, headers)
    enter(client, headers, event["id"], players(4))
    assert draw(client, headers, event).status_code == 200
    stage = event["stages"][0]["id"]
    first = client.get(f"/events/{event['id']}/stages/{stage}/series").json()
    walkover = client.put(
        f"/cup-series/{first['series'][0]['id']}/result-kind",
        json={"result_kind": "walkover", "winner": 1},
        headers=headers,
    )
    assert walkover.status_code == 200, walkover.text
    finished = client.post(f"/events/{event['id']}/finish", headers=headers)
    assert finished.status_code == 200, finished.text
    with Session.begin() as session:
        session.add_all(
            [
                DiscordPost(
                    kind=kind, subject_id=subject, channel_id="1", message_id=message
                )
                for kind, subject, message in (
                    ("cup_open", event["id"], "11"),
                    ("cup_draw", stage, "12"),
                    ("announce", event["id"], "13"),
                )
            ]
        )

    path = f"/events/{event['id']}"
    assert client.delete(path, headers=member("51")).status_code == 403
    gone = client.delete(path, headers=headers)
    assert gone.status_code == 204, gone.text
    assert client.get(path, headers=auth_headers).status_code == 404

    with Session() as session:
        assert session.scalars(select(CupSeries)).all() == []
        for column in (
            EventEntrant.event_id,
            EventAward.event_id,
            CupSettings.event_id,
            EventOrganizer.event_id,
        ):
            left = select(column).where(col(column) == event["id"])
            assert session.scalars(left).all() == [], column
        posts = session.scalars(select(DiscordPost)).all()
        assert [(post.kind, post.subject_id) for post in posts] == [
            ("announce", event["id"])
        ]


def test_an_admin_deletes_an_organizers_cup(
    client: Client, auth_headers: Headers, member: Member
) -> None:
    grant(client, auth_headers, "50")
    event = create(client, member("50"))

    gone = client.delete(f"/events/{event['id']}", headers=auth_headers)

    assert gone.status_code == 204, gone.text
    assert client.get(f"/events/{event['id']}", headers=auth_headers).status_code == 404


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
    mine = client.get("/me/organized-events", headers=headers)
    assert mine.status_code == 200
    assert [row["id"] for row in mine.json()] == [event["id"]]
    assert client.get("/me/organized-events", headers=member("90")).json() == []


def test_the_organized_events_read_as_the_events_list_does(
    client: Client, auth_headers: Headers, member: Member
) -> None:
    """Newest start first, each row with its archived flag."""
    grant(client, auth_headers, "50")
    headers = member("50")
    later = create(client, headers, name="Late Cup", start_date="2026-11-20")
    sooner = create(client, headers, name="Early Cup", start_date="2026-11-06")
    mine = client.get("/me/organized-events", headers=headers)
    assert mine.status_code == 200, mine.text
    assert [(row["id"], row["archived"]) for row in mine.json()] == [
        (later["id"], False),
        (sooner["id"], False),
    ]


def test_the_organized_events_count_who_is_in_checked_in_and_waiting(
    client: Client, auth_headers: Headers, member: Member
) -> None:
    """Players are counted once each: in (neither withdrawn nor waiting),
    checked in among them, and waiting; a withdrawn row counts nowhere."""
    from app.models.event_entrant import EventEntrant
    from app.models.types import utcnow

    grant(client, auth_headers, "50")
    headers = member("50")
    busy = create(client, headers, name="Busy Cup")
    create(client, headers, name="Empty Cup")
    checked, signed, waiting, gone = players(4)
    enter(client, auth_headers, busy["id"], [checked, signed, waiting, gone])
    with Session.begin() as session:
        rows = {
            row.user_id: row
            for row in session.scalars(
                select(EventEntrant).where(EventEntrant.event_id == busy["id"])
            )
        }
        rows[checked].checked_in_at = utcnow()
        rows[waiting].waitlisted_at = utcnow()
        rows[gone].withdrawn_at = utcnow()

    mine = client.get("/me/organized-events", headers=headers)
    assert mine.status_code == 200, mine.text
    counts = {
        row["name"]: (
            row["entrant_count"],
            row["checked_in_count"],
            row["waitlist_count"],
        )
        for row in mine.json()
    }
    assert counts == {"Busy Cup": (2, 1, 1), "Empty Cup": (0, 0, 0)}


def test_the_organizer_routes_are_mounted_once(app: FastAPI) -> None:
    """A router included twice names each of its operations twice."""
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        get_openapi(title=app.title, version=app.version, routes=app.routes)
    messages = [str(w.message) for w in caught]
    assert [m for m in messages if m.startswith("Duplicate Operation ID")] == []


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


def test_a_finished_cup_takes_no_series_write_until_it_is_reopened(
    client: Client, auth_headers: Headers, member: Member
) -> None:
    """Every write on a series of a finished or called off cup answers 400,
    to its runner and its players alike; its reads still answer, and a reopen
    takes writes again."""
    grant(client, auth_headers, "50")
    headers = member("50")
    event = create(client, headers)
    enter(client, headers, event["id"], players(2))
    assert draw(client, headers, event).status_code == 200
    with Session.begin() as session:
        series = session.scalars(select(CupSeries)).one()
        series_id = series.id
        loser = member(session.get_one(User, series.player2_id).discordId)
    path = f"/cup-series/{series_id}"
    won = {"player1_score": 2, "player2_score": 0}
    turned = {"player1_score": 0, "player2_score": 2}
    assert client.put(path, json=won, headers=headers).status_code == 200
    writes = [
        ("PUT", f"{path}/report", turned),
        ("PUT", path, won),
        ("DELETE", f"{path}/result", None),
        ("PUT", f"{path}/result-kind", {"result_kind": "walkover", "winner": 1}),
        ("PUT", f"{path}/places", {"places": []}),
        ("PUT", f"{path}/lobby-map", {"map_id": 1}),
        ("PUT", f"{path}/sides", {"entrant_ids": []}),
        ("POST", f"{path}/move", {"entrant_id": 1, "to_series_id": series_id}),
        ("PUT", f"{path}/veto", {"action": "undo"}),
    ]

    for close in ("finish", "cancel"):
        closed = client.post(f"/events/{event['id']}/{close}", headers=headers)
        assert closed.status_code == 200, closed.text
        for caller in (headers, loser):
            for method, url, body in writes:
                refused = client.request(method, url, json=body, headers=caller)
                assert refused.status_code == 400, (url, refused.text)
                assert refused.json() == {
                    "error": "The cup is finished; reopen it first"
                }
        for url in (path, f"{path}/games"):
            assert client.get(url).status_code == 200
        reopened = client.post(f"/events/{event['id']}/reopen", headers=headers)
        assert reopened.status_code == 200, reopened.text

    flipped = client.put(f"{path}/report", json=turned, headers=loser)
    assert flipped.status_code == 200, flipped.text


# --- the organizer picker's search ---


def person(
    name: str, discord_id: str | None, tag: str | None = None, banned: bool = False
) -> int:
    """A player row, with a Discord login when it has an id."""
    from app.models.enums import Race
    from app.models.types import utcnow

    with Session.begin() as session:
        user = User(
            name=name,
            discordId=discord_id,
            discordTag=tag,
            race=Race.HU,
            banned_at=utcnow() if banned else None,
        )
        session.add(user)
        session.flush()
        assert user.id is not None
        return user.id


def names(response: Any) -> list[str]:  # noqa: ANN401
    assert response.status_code == 200, response.text
    return [row["name"] for row in response.json()]


def test_a_runner_finds_players_by_name_or_discord_tag(
    client: Client, auth_headers: Headers, member: Member
) -> None:
    grant(client, auth_headers, "50")
    creator = member("50")
    event = create(client, creator)
    person("Quillfeather", "81", "quill.writes")
    person("Ironhoof", "82", "hoofbeat")
    person("Mistveil", "83", "QUILLSTORM")
    path = f"/events/{event['id']}/organizer-candidates"

    found = client.get(path, params={"q": "QUILL"}, headers=creator)
    # a name or tag that starts with the text first, in name order, any case
    assert names(found) == ["Mistveil", "Quillfeather"]
    row = found.json()[1]
    assert row["discord_id"] == "81" and row["discord_tag"] == "quill.writes"
    assert row["user_id"] > 0
    assert names(client.get(path, params={"q": "beat"}, headers=creator)) == [
        "Ironhoof"
    ]


def test_the_search_skips_runners_logins_missing_and_bans(
    client: Client, auth_headers: Headers, member: Member
) -> None:
    grant(client, auth_headers, "50")
    creator = member("50")
    event = create(client, creator)
    person("Ashfall One", "84", "ash1")
    person("Ashfall Two", None)
    person("Ashfall Three", "85", "ash3", banned=True)
    person("Ashfall Four", "86", "ash4")
    added = client.post(
        f"/events/{event['id']}/organizers",
        json={"discord_id": "86"},
        headers=creator,
    )
    assert added.status_code == 201, added.text
    path = f"/events/{event['id']}/organizer-candidates"
    assert names(client.get(path, params={"q": "ashfall"}, headers=creator)) == [
        "Ashfall One"
    ]


def test_the_search_answers_ten_at_most_and_reads_a_wildcard_as_itself(
    client: Client, auth_headers: Headers
) -> None:
    for index in range(12):
        person(f"Northgate {index:02}", str(900 + index))
    person("Half%Moon", "950")
    person("Halfling", "951")
    path = "/organizers/candidates"
    assert (
        len(names(client.get(path, params={"q": "north"}, headers=auth_headers))) == 10
    )
    assert names(client.get(path, params={"q": "f%m"}, headers=auth_headers)) == [
        "Half%Moon"
    ]


def test_the_grant_search_skips_organizers_and_is_for_admins_only(
    client: Client, auth_headers: Headers, member: Member
) -> None:
    person("Thornwick", "87", "thorn")
    person("Thornbury", "88", "bury")
    grant(client, auth_headers, "88")
    path = "/organizers/candidates"
    assert names(client.get(path, params={"q": "thorn"}, headers=auth_headers)) == [
        "Thornwick"
    ]
    assert (
        client.get(path, params={"q": "thorn"}, headers=member("70")).status_code == 403
    )
    assert client.get(path, params={"q": "t"}, headers=auth_headers).status_code == 422


def test_only_a_runner_searches_an_events_candidates(
    client: Client, auth_headers: Headers, member: Member
) -> None:
    grant(client, auth_headers, "50")
    event = create(client, member("50"))
    path = f"/events/{event['id']}/organizer-candidates"
    assert client.get(path, params={"q": "ab"}, headers=member("71")).status_code == 403
    assert client.get(path, params={"q": "ab"}, headers=auth_headers).status_code == 200
