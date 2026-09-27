"""The local dev login signs in as any player that has a Discord id, and only while it is on."""

from typing import Any

import pytest
from httpx2 import Client

from tests.test_player_session import SIGNUP_BODY
from tests.test_seats import _captain


@pytest.fixture
def dev_on(monkeypatch: pytest.MonkeyPatch) -> None:
    """DEV_LOGIN on a machine that is no deployment, with no bot token to call Discord."""
    monkeypatch.setenv("DEV_LOGIN", "1")
    monkeypatch.delenv("VERCEL", raising=False)
    monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
    monkeypatch.setenv("ADMIN_DISCORD_IDS", "")


def _sign_in(
    client: Client, admin: dict[str, str], user_id: int, role: str = "member"
) -> dict[str, str]:
    answer = client.post(
        "/dev/login", json={"user_id": user_id, "role": role}, headers=admin
    )
    assert answer.status_code == 200, answer.text
    return {"Authorization": f"Bearer {answer.json()['access_token']}"}


def test_everything_answers_404_while_the_dev_login_is_off(
    client: Client,
    seeded: dict[str, Any],
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Off by default, even to the admin token; a token minted while it was on is refused once it is off."""
    monkeypatch.delenv("DEV_LOGIN", raising=False)
    user_id = seeded["player_ids"][0]
    for headers in ({}, auth_headers):
        assert client.get("/dev/players", headers=headers).status_code == 404
        answer = client.post("/dev/login", json={"user_id": user_id}, headers=headers)
        assert answer.status_code == 404

    monkeypatch.setenv("DEV_LOGIN", "1")
    headers = _sign_in(client, auth_headers, user_id)
    monkeypatch.delenv("DEV_LOGIN")
    assert client.get("/me", headers=headers).status_code == 422


def test_a_deployment_never_answers_even_with_the_switch_on(
    client: Client,
    seeded: dict[str, Any],
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("DEV_LOGIN", "1")
    monkeypatch.setenv("VERCEL", "1")
    assert client.get("/dev/players", headers=auth_headers).status_code == 404
    answer = client.post(
        "/dev/login", json={"user_id": seeded["player_ids"][0]}, headers=auth_headers
    )
    assert answer.status_code == 404


def test_only_the_admin_token_reaches_the_dev_login(
    client: Client, seeded: dict[str, Any], auth_headers: dict[str, str], dev_on: None
) -> None:
    """No session is 401; a dev session, even an admin one, is 403, so a player never switches."""
    user_id = seeded["player_ids"][0]
    assert client.get("/dev/players").status_code == 401
    assert client.post("/dev/login", json={"user_id": user_id}).status_code == 401

    for role in ("member", "admin"):
        headers = _sign_in(client, auth_headers, user_id, role=role)
        assert client.get("/dev/players", headers=headers).status_code == 403
        answer = client.post("/dev/login", json={"user_id": user_id}, headers=headers)
        assert answer.status_code == 403


def test_a_member_login_is_that_player(
    client: Client, seeded: dict[str, Any], auth_headers: dict[str, str], dev_on: None
) -> None:
    """The player's own /me and games; never the super admin."""
    headers = _sign_in(client, auth_headers, seeded["player_ids"][0])

    me = client.get("/me", headers=headers).json()

    assert me["role"] == "member"
    assert me["superadmin"] is False
    assert me["name"] == "P1"
    assert me["user"]["id"] == seeded["player_ids"][0]
    games = client.get(
        f"/player-series?season_id={seeded['season_id']}", headers=headers
    )
    assert games.status_code == 200, games.text
    assert games.json()["player"]["id"] == seeded["player_ids"][0]


def test_a_player_with_a_seat_is_a_captain(
    client: Client, seeded: dict[str, Any], auth_headers: dict[str, str], dev_on: None
) -> None:
    _captain(seeded["team_a_id"], seeded["season_id"], seeded["player_ids"][0])
    headers = _sign_in(client, auth_headers, seeded["player_ids"][0])

    me = client.get("/me", headers=headers).json()

    assert me["role"] == "captain"
    assert me["seats"] == [
        {"team_id": seeded["team_a_id"], "season_id": seeded["season_id"]}
    ]


def test_a_guest_login_reads_nothing_of_its_own(
    client: Client, seeded: dict[str, Any], auth_headers: dict[str, str], dev_on: None
) -> None:
    headers = _sign_in(client, auth_headers, seeded["player_ids"][0], role="guest")

    assert client.get("/me", headers=headers).json()["role"] == "guest"
    assert client.post("/signup", json=SIGNUP_BODY, headers=headers).status_code == 403


def test_an_admin_login_keeps_the_seats_and_can_view_as(
    client: Client, seeded: dict[str, Any], auth_headers: dict[str, str], dev_on: None
) -> None:
    _captain(seeded["team_a_id"], seeded["season_id"], seeded["player_ids"][0])
    headers = _sign_in(client, auth_headers, seeded["player_ids"][0], role="admin")

    me = client.get("/me", headers=headers).json()
    assert me["role"] == "admin"
    assert me["superadmin"] is False
    assert me["seats"] == [
        {"team_id": seeded["team_a_id"], "season_id": seeded["season_id"]}
    ]

    viewed = client.get("/me", headers=headers | {"X-View-As": "member"}).json()
    assert viewed["role"] == "member"
    assert viewed["actual_role"] == "admin"
    assert viewed["seats"] == []


def test_the_player_list_marks_captains_and_leaves_out_players_without_a_discord_id(
    client: Client, seeded: dict[str, Any], auth_headers: dict[str, str], dev_on: None
) -> None:
    from app.core.db import Session
    from app.models.enums import Race
    from app.models.user import User

    with Session.begin() as session:
        session.add_all(
            [
                User(name="No Login", discordId=None, race=Race.HU),
                User(name="Stand In", discordId="gnl-17", race=Race.OC),
            ]
        )
    _captain(seeded["team_a_id"], seeded["season_id"], seeded["player_ids"][1])

    players = client.get("/dev/players", headers=auth_headers).json()
    names = [player["name"] for player in players]

    assert "No Login" not in names
    assert "Stand In" not in names
    assert {player["name"]: player["captain"] for player in players}["P2"] is True
    searched = client.get("/dev/players?search=p3", headers=auth_headers).json()
    assert searched[0]["name"] == "P3"
    stand_in = client.post("/dev/login", json={"user_id": 999999}, headers=auth_headers)
    assert stand_in.status_code == 400
