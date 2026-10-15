"""The member home's events side: a cup team counts as joined, a team cup takes
no solo signup, and GET /me/cup-series lists what the caller still plays.

The home reads its cups off GET /me/events and its open matches off one read,
GET /me/cup-series: a two-sided series the caller plays a side of, and a lobby
the caller sits in, alone or in a seated team.
"""

from typing import Any

import pytest
from httpx2 import Client

from app.core.db import Session
from app.models.enums import StageFormat
from app.models.relationships import DBMapSeason
from app.models.season import Season
from tests.test_cup_best_of import maps
from tests.test_event_organizers import Headers, Member
from tests.test_ffa import discord_of, ffa, lobbies
from tests.test_stage_engine import cup as solo_cup
from tests.test_stage_engine import generate, players, players_of, team_cup
from tests.test_team_cups import accept, cup, headers_of, no_refresh, sign_up


def row_of(client: Client, headers: Headers, event: int) -> dict[str, Any]:
    response = client.get("/me/events", headers=headers)
    assert response.status_code == 200, response.text
    return next(row for row in response.json() if row["id"] == event)


def open_series(client: Client, headers: Headers) -> list[dict[str, Any]]:
    response = client.get("/me/cup-series", headers=headers)
    assert response.status_code == 200, response.text
    return response.json()


def test_a_player_of_a_cup_team_reads_the_cup_as_joined(
    client: Client, member: Member, monkeypatch: pytest.MonkeyPatch
) -> None:
    no_refresh(monkeypatch)
    event = cup()
    captain, mate = players(2)
    made = sign_up(client, event, headers_of(member, captain), "Blue", mate)
    assert made.status_code == 201, made.text
    team = made.json()["team"]["id"]

    led = row_of(client, headers_of(member, captain), event)
    assert led["joined"] is True
    assert led["team_size"] == 2
    assert led["cup_team"] == {
        "id": team,
        "name": "Blue",
        "captain": True,
        "players": 1,
    }
    assert led["entrant_id"] == made.json()["id"]
    # the team leaves on its own panel, so the home offers its players no withdraw
    assert led["action"] == "view"

    # an invited player has not joined yet, and still reads the cup as open
    invited = row_of(client, headers_of(member, mate), event)
    assert invited["joined"] is False
    assert invited["cup_team"] is None
    assert invited["action"] == "sign_up"

    accept(client, event, team, headers_of(member, mate))
    joined = row_of(client, headers_of(member, mate), event)
    assert joined["joined"] is True
    assert joined["cup_team"] == {
        "id": team,
        "name": "Blue",
        "captain": False,
        "players": 2,
    }


def test_a_team_cup_refuses_a_players_own_signup(
    client: Client, member: Member, monkeypatch: pytest.MonkeyPatch
) -> None:
    no_refresh(monkeypatch)
    event = cup()
    [player] = players(1)
    refused = client.post(
        f"/events/{event}/entrants",
        json={"race": "HU"},
        headers=headers_of(member, player),
    )
    assert refused.status_code == 400, refused.text
    assert "sign a team up" in refused.text
    assert row_of(client, headers_of(member, player), event)["joined"] is False


def test_the_member_row_names_the_cup_format(
    client: Client, member: Member, monkeypatch: pytest.MonkeyPatch
) -> None:
    no_refresh(monkeypatch)
    event, _, _ = ffa(4)
    two_sided = cup(size=3, name="Trio Cup")
    headers = member(discord_of(players_of(event)[0]))
    lobby = row_of(client, headers, event)
    assert (lobby["ffa"], lobby["custom_game"], lobby["team_size"]) == (
        True,
        False,
        None,
    )
    trio = row_of(client, headers, two_sided)
    assert (trio["ffa"], trio["team_size"]) == (False, 3)


def test_a_player_reads_their_open_series_and_not_the_played_ones(
    client: Client, member: Member, auth_headers: Headers
) -> None:
    event, [stage] = solo_cup(4)
    generate(client, auth_headers, event, stage)

    first, second, third, fourth = players_of(event)
    mine = open_series(client, member(discord_of(first)))
    assert len(mine) == 1
    [row] = mine
    assert row["event_id"] == event
    assert row["event_name"] == "Autumn Cup"
    assert row["stage_id"] == stage
    assert row["round_number"] == 1
    assert first in (row["series"]["player1_id"], row["series"]["player2_id"])
    # the final waits for both semifinals, so it is no one's to play yet
    assert all(row["series"]["entrant1_id"] for row in mine)

    scored = client.put(
        f"/cup-series/{row['series']['id']}",
        json={"player1_score": 2, "player2_score": 0},
        headers=auth_headers,
    )
    assert scored.status_code == 200, scored.text
    played = {row["series"]["player1_id"], row["series"]["player2_id"]}
    for player in played:
        assert open_series(client, member(discord_of(player))) == []
    others = [player for player in (second, third, fourth) if player not in played]
    for player in others:
        assert len(open_series(client, member(discord_of(player)))) == 1

    # an unpublished cup lists nothing
    with Session.begin() as session:
        held = session.get(Season, event)
        assert held is not None
        held.published = False
    assert open_series(client, member(discord_of(others[0]))) == []


def test_every_player_of_a_team_reads_the_teams_open_series(
    client: Client, member: Member, auth_headers: Headers
) -> None:
    event, stage, _, tags = team_cup(client, auth_headers, member)
    generate(client, auth_headers, event, stage)
    for captain, mate in tags:
        led = open_series(client, member(captain))
        assert len(led) == 1
        assert open_series(client, member(mate)) == led
        box = led[0]["series"]
        assert box["team1"]["name"] and box["team2"]["name"]


def test_a_seated_player_reads_their_lobby_and_not_the_rounds_below(
    client: Client, member: Member, auth_headers: Headers
) -> None:
    event, bracket, _ = ffa()
    generate(client, auth_headers, event, bracket)
    first = lobbies(client, event, bracket, "Round 1")[0]
    player = first["sides"][0]["user_id"]
    # the rounds below wait for their players, so only the seated lobby is listed
    [row] = open_series(client, member(discord_of(player)))
    assert row["series"]["id"] == first["id"]
    assert len(row["series"]["sides"]) == 4
    assert row["series"]["lobby_map"] is not None


def test_a_player_of_a_seated_team_reads_its_lobby(
    client: Client, member: Member, auth_headers: Headers
) -> None:
    event, stage, _, tags = team_cup(
        client,
        auth_headers,
        member,
        StageFormat.ffa,
        lobby_size=4,
        swiss_rounds=2,
        points_by_place="3,2,1,0",
    )
    with Session.begin() as session:
        session.add_all(
            DBMapSeason(season_id=event, map_id=map_id, position=position)
            for position, map_id in enumerate(maps(2))
        )
    generate(client, auth_headers, event, stage)
    rows = open_series(client, member(tags[1][1]))
    # the league plays two games in one lobby, both seated from the start
    assert len(rows) == 2
    assert all(len(row["series"]["sides"]) == 4 for row in rows)
    assert all(seat["team"] for row in rows for seat in row["series"]["sides"])
    assert open_series(client, member("99990")) == []


def test_a_team_checks_in_once_every_player_accepted(
    client: Client, member: Member, monkeypatch: pytest.MonkeyPatch
) -> None:
    no_refresh(monkeypatch)
    event = cup()
    captain, mate = players(2)
    made = sign_up(client, event, headers_of(member, captain), "Blue", mate)
    assert made.status_code == 201, made.text
    entrant, team = made.json()["id"], made.json()["team"]["id"]

    early = client.post(
        f"/events/{event}/entrants/{entrant}/checkin",
        headers=headers_of(member, captain),
    )
    assert early.status_code == 400, early.text
    assert "accepted their invitation" in early.text

    accept(client, event, team, headers_of(member, mate))
    checked = client.post(
        f"/events/{event}/entrants/{entrant}/checkin",
        headers=headers_of(member, captain),
    )
    assert checked.status_code == 200, checked.text


def test_a_round_takes_a_team_once_every_player_accepted(
    client: Client,
    member: Member,
    auth_headers: Headers,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from tests.test_cup_divisions import make_cup
    from tests.test_cup_rounds import LEGS, check_in, legs_of, player_with_login

    no_refresh(monkeypatch)
    made_cup = make_cup(
        client,
        auth_headers,
        legs=LEGS,
        team_size=2,
        published=True,
        signups_open=True,
    )
    event = made_cup["id"]
    player_with_login("81", 1800)
    mate = player_with_login("82", 1700)
    made = sign_up(client, event, member("81"), "Blue", mate)
    assert made.status_code == 201, made.text
    entrant, team = made.json()["id"], made.json()["team"]["id"]
    leg = legs_of(client, event)[0]["id"]

    early = check_in(client, member("81"), event, leg)
    assert early.status_code == 400, early.text
    # a runner's check-in of everyone leaves the short team out
    everyone = client.post(
        f"/events/{event}/legs/{leg}/checkins/everyone", headers=auth_headers
    )
    assert everyone.status_code == 200, everyone.text
    assert everyone.json()[0]["checked_in"] == []

    accept(client, event, team, member("82"))
    checked = check_in(client, member("81"), event, leg)
    assert checked.status_code == 200, checked.text
    assert checked.json()[0]["checked_in"] == [entrant]
