"""Team cups: a captain signs a team up for one cup and every teammate confirms.

The team is a team row made for that cup; its roster holds confirmed players
only, an invited player waits until they answer, and the draw plays the team
entrants as team sides of the cup's size. Any member acts for the team.
"""

from typing import Any

import pytest
from httpx2 import Client, Response
from sqlmodel import col, select

from app.core.db import Session
from app.models.enums import EventKind, LeagueKind, Race
from app.models.league import League
from app.models.season import Season
from app.models.series import Series
from app.models.w3c_stats import W3CStats
from tests.test_event_organizers import Headers, Member, grant
from tests.test_stage_engine import players


def cup(size: int = 2, **fields: Any) -> int:  # noqa: ANN401
    """A published team cup with signups open."""
    with Session.begin() as session:
        event = Season(
            name=fields.pop("name", "Team Cup"),
            kind=EventKind.cup,
            series_per_round=1,
            published=True,
            signups_open=True,
            team_size=size,
            **fields,
        )
        session.add(event)
        session.flush()
        assert event.id is not None
        return event.id


def headers_of(member: Member, user_id: int) -> Headers:
    """The headers of the test player with that id; players() numbers the Discord ids."""
    with Session.begin() as session:
        from app.models.user import User

        user = session.get(User, user_id)
        assert user is not None and user.discordId is not None
        return member(user.discordId)


def sign_up(
    client: Client, event: int, headers: Headers, name: str, *mates: int
) -> Response:
    return client.post(
        f"/events/{event}/cup-teams",
        json={"name": name, "member_ids": list(mates)},
        headers=headers,
    )


def entrants(client: Client, event: int) -> list[dict[str, Any]]:
    response = client.get(f"/events/{event}/entrants")
    assert response.status_code == 200, response.text
    return response.json()


def accept(client: Client, event: int, team: int, headers: Headers) -> None:
    response = client.post(f"/events/{event}/cup-teams/{team}/accept", headers=headers)
    assert response.status_code == 204, response.text


def no_refresh(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services import events

    monkeypatch.setattr(events, "refresh_rating", lambda *args: None)


def test_a_captain_signs_a_team_up_and_the_teammate_confirms(
    client: Client, member: Member, monkeypatch: pytest.MonkeyPatch
) -> None:
    no_refresh(monkeypatch)
    event = cup()
    captain, mate, other = players(3)

    made = sign_up(client, event, headers_of(member, captain), "Blue", mate)
    assert made.status_code == 201, made.text
    team = made.json()["team"]["id"]
    assert made.json()["team"]["league_id"] is None
    [row] = entrants(client, event)
    assert [one["user"]["id"] for one in row["roster"]] == [captain]
    assert row["roster"][0]["captain"] is True
    assert [one["id"] for one in row["invited"]] == [mate]

    invites = client.get("/me/team-invites", headers=headers_of(member, mate))
    assert invites.status_code == 200, invites.text
    assert [(one["event_id"], one["team"]["name"]) for one in invites.json()] == [
        (event, "Blue")
    ]
    assert invites.json()[0]["captain"]["id"] == captain

    # a decline frees the place, and the captain invites someone else
    declined = client.post(
        f"/events/{event}/cup-teams/{team}/decline", headers=headers_of(member, mate)
    )
    assert declined.status_code == 204, declined.text
    again = client.post(
        f"/events/{event}/cup-teams/{team}/invites",
        json={"user_id": other},
        headers=headers_of(member, captain),
    )
    assert again.status_code == 204, again.text
    accept(client, event, team, headers_of(member, other))
    [row] = entrants(client, event)
    assert sorted(one["user"]["id"] for one in row["roster"]) == sorted(
        [captain, other]
    )
    assert row["invited"] == []

    # any member checks the team in
    checked = client.post(
        f"/events/{event}/entrants/{row['id']}/checkin",
        headers=headers_of(member, other),
    )
    assert checked.status_code == 200, checked.text


def test_a_player_plays_for_one_team_of_a_cup_and_a_team_fields_its_size(
    client: Client, member: Member, monkeypatch: pytest.MonkeyPatch
) -> None:
    no_refresh(monkeypatch)
    event = cup(entrant_cap=1)
    first, second, third, fourth = players(4)

    short = sign_up(client, event, headers_of(member, first), "Short")
    assert short.status_code == 400
    assert "fields 2 players" in short.text

    assert (
        sign_up(client, event, headers_of(member, first), "Blue", second).status_code
        == 201
    )
    taken = sign_up(client, event, headers_of(member, third), "Red", second)
    assert taken.status_code == 400
    assert "already plays for a team" in taken.text
    # a full cup takes the next team onto its waitlist
    full = sign_up(client, event, headers_of(member, third), "Red", fourth)
    assert full.status_code == 201, full.text
    assert full.json()["waitlisted_at"] is not None


def test_a_removed_team_frees_the_players_it_invited(
    client: Client,
    member: Member,
    auth_headers: Headers,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    no_refresh(monkeypatch)
    event = cup()
    captain, invited, other = players(3)
    made = sign_up(client, event, headers_of(member, captain), "Red", invited)
    assert made.status_code == 201, made.text

    removed = client.delete(
        f"/events/{event}/entrants/{made.json()['id']}", headers=auth_headers
    )
    assert removed.status_code == 204, removed.text
    invites = client.get("/me/team-invites", headers=headers_of(member, invited))
    assert invites.status_code == 200, invites.text
    assert invites.json() == []
    joined = sign_up(client, event, headers_of(member, other), "Blue", invited)
    assert joined.status_code == 201, joined.text


def test_every_player_is_held_to_the_cups_eligibility(
    client: Client, member: Member, monkeypatch: pytest.MonkeyPatch
) -> None:
    no_refresh(monkeypatch)
    event = cup(eligibility_required=True, race_games_min=20, mmr_max=1000)
    captain, mate = players(2)
    with Session.begin() as session:
        session.add_all(
            [
                W3CStats(
                    user_id=captain, race=Race.NE, wc3_season=22, games=40, mmr=900
                ),
                W3CStats(user_id=mate, race=Race.HU, wc3_season=22, games=40, mmr=1500),
            ]
        )

    refused = sign_up(client, event, headers_of(member, captain), "Blue", mate)
    assert refused.status_code == 400
    assert "rated 1500" in refused.text


def test_a_team_cup_draws_complete_teams_and_any_member_reports(
    client: Client,
    member: Member,
    auth_headers: Headers,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    no_refresh(monkeypatch)
    event = cup(name="Draw Cup")
    with Session.begin() as session:
        from app.models.enums import StageFormat
        from app.models.event_stage import EventStage

        stage = EventStage(
            event_id=event, format=StageFormat.single_elimination, best_of=1
        )
        session.add(stage)
        session.flush()
        stage_id = stage.id
    ids = players(8)
    teams = []
    for index in range(4):
        captain, mate = ids[2 * index], ids[2 * index + 1]
        made = sign_up(client, event, headers_of(member, captain), f"T{index}", mate)
        assert made.status_code == 201, made.text
        teams.append((made.json()["team"]["id"], captain, mate))

    # one team still waits for its second player
    seeds = client.put(
        f"/events/{event}/stages/{stage_id}/seeds",
        json={"source": "mmr"},
        headers=auth_headers,
    )
    assert seeds.status_code == 200, seeds.text
    refused = client.post(
        f"/events/{event}/stages/{stage_id}/generate", headers=auth_headers
    )
    assert refused.status_code == 400
    assert "T0" in refused.text
    for team, _, mate in teams:
        accept(client, event, team, headers_of(member, mate))
    drawn = client.post(
        f"/events/{event}/stages/{stage_id}/generate", headers=auth_headers
    )
    assert drawn.status_code == 200, drawn.text

    with Session.begin() as session:
        rows = session.scalars(
            select(Series).where(
                col(Series.entrant1_id).is_not(None),
                col(Series.entrant2_id).is_not(None),
            )
        ).all()
        assert rows and all(row.side_size == 2 for row in rows)
        first = rows[0]
        series_id, entrant = first.id, first.entrant1_id
    # the teammate who is not the captain reports for the team
    by_entrant = {row["id"]: row for row in entrants(client, event)}
    reporter = next(
        one["user"]["id"] for one in by_entrant[entrant]["roster"] if not one["captain"]
    )
    # the veto board lists a team side's players, so a step one of them enters is the side's own
    board = client.get(
        f"/player-series/{series_id}/veto", headers=headers_of(member, reporter)
    )
    assert board.status_code == 200, board.text
    assert board.json()["player1"]["member_ids"] == sorted(
        one["user"]["id"] for one in by_entrant[entrant]["roster"]
    )
    report = client.put(
        f"/player-series/{series_id}",
        json={"player1_score": 1, "player2_score": 0},
        headers=headers_of(member, reporter),
    )
    assert report.status_code == 200, report.text


def test_a_runner_swaps_a_player_until_the_team_plays(
    client: Client,
    member: Member,
    auth_headers: Headers,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    no_refresh(monkeypatch)
    event = cup()
    captain, mate, late = players(3)
    made = sign_up(client, event, headers_of(member, captain), "Blue", mate)
    team = made.json()["team"]["id"]
    accept(client, event, team, headers_of(member, mate))

    swapped = client.post(
        f"/events/{event}/cup-teams/{team}/members/{captain}/replace",
        json={"user_id": late},
        headers=auth_headers,
    )
    assert swapped.status_code == 200, swapped.text
    roster = swapped.json()["roster"]
    # the new player takes the captaincy with the place
    assert roster[0]["user"]["id"] == late and roster[0]["captain"] is True
    assert {one["user"]["id"] for one in roster} == {late, mate}


def test_a_cup_team_stays_out_of_its_leagues_team_lists(
    client: Client, member: Member, monkeypatch: pytest.MonkeyPatch
) -> None:
    no_refresh(monkeypatch)
    with Session.begin() as session:
        league = League(name="Cup League", short_name="CL", kind=LeagueKind.custom)
        session.add(league)
        session.flush()
        league_id = league.id
    event = cup(league_id=league_id)
    captain, mate = players(2)
    made = sign_up(client, event, headers_of(member, captain), "Blue", mate)
    assert made.status_code == 201, made.text
    assert made.json()["team"]["league_id"] == league_id
    listed = client.get(f"/leagues/{league_id}/teams")
    assert listed.status_code == 200, listed.text
    assert all(team["name"] != "Blue" for team in listed.json())


def test_an_organizer_reads_the_team_ladder_pool(
    client: Client, auth_headers: Headers, member: Member
) -> None:
    grant(client, auth_headers, "91")
    refused = client.get("/maps/ladder-import?mode=3v3", headers=member("91"))
    assert refused.status_code == 422
