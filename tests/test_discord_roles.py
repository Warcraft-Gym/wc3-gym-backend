"""What the database says a Discord account should hold, and the sync of it.

The guild is stood in for: `discord.requests.request` answers the member read
and records the role writes. Without DISCORD_BOT_TOKEN nothing is called at
all, and the suite fails any call a test did not stand in for.
"""

from typing import Any

import pytest
from httpx2 import Client

from app.core.db import Session
from app.models.admin_grant import AdminGrant
from app.models.base import ident
from app.models.discord_role_binding import DiscordRoleBinding
from app.models.enums import RoleKind
from app.models.relationships import DBTeamSeasonCaptain, DBUserSeasonSignup
from app.models.season import Season
from app.models.settings import Settings
from app.models.user import User
from app.services import discord, discord_roles
from tests.test_discord_auth import GUILD_ID, FakeResponse

MEMBERS = f"{discord.API_URL}/guilds/{GUILD_ID}/members"


def _bind(kind: RoleKind, role: str, **columns: int) -> None:
    with Session() as session:
        session.add(DiscordRoleBinding(kind=kind, discord_role=role, **columns))
        session.commit()


def _expected(user_id: int) -> set[str]:
    with Session() as session:
        user = session.get(User, user_id)
        assert user
        return discord_roles.expected_roles(user, session)


def _captain(team_id: int, season_id: int, user_id: int) -> None:
    with Session() as session:
        session.add(
            DBTeamSeasonCaptain(team_id=team_id, season_id=season_id, user_id=user_id)
        )
        session.commit()


def _guild(
    monkeypatch: pytest.MonkeyPatch, roles: dict[str, list[str]]
) -> list[tuple[str, str]]:
    """Answer the member reads with those roles and record every call."""
    calls: list[tuple[str, str]] = []

    def request(method: str, url: str, **kwargs: object) -> FakeResponse:
        calls.append((method, url))
        return FakeResponse(200, {"roles": roles.get(url.rsplit("/", 1)[-1], [])})

    monkeypatch.setenv("DISCORD_BOT_TOKEN", "a-bot-token")
    monkeypatch.setenv("DISCORD_GUILD_ID", GUILD_ID)
    monkeypatch.setattr(discord.requests, "request", request)
    return calls


def test_a_grant_earns_the_admin_role(seeded: dict[str, Any]) -> None:
    """The app names the admins, and the guild role only mirrors them."""
    _bind(RoleKind.admin, "admin-role")
    with Session() as session:
        session.add(AdminGrant(discord_id="1", granted_by="admin"))
        session.commit()

    assert _expected(seeded["player_ids"][0]) == {"admin-role"}
    assert _expected(seeded["player_ids"][1]) == set()


def test_granting_an_admin_writes_the_guild_role(
    client: Client,
    monkeypatch: pytest.MonkeyPatch,
    auth_headers: dict[str, str],
    seeded: dict[str, Any],
) -> None:
    """The grant takes its name from the users row and mirrors the bound role."""
    _bind(RoleKind.admin, "admin-role")
    calls = _guild(monkeypatch, {})

    resp = client.post("/config/admins", json={"discord_id": "1"}, headers=auth_headers)

    assert resp.status_code == 201, resp.text
    assert resp.json()["name"] == "P1"
    assert calls == [("GET", f"{MEMBERS}/1"), ("PUT", f"{MEMBERS}/1/roles/admin-role")]


def test_a_signup_earns_the_participant_role(seeded: dict[str, Any]) -> None:
    """A player signed up for the season earns it with no roster row."""
    _bind(RoleKind.gnl_participant, "gnl")
    with Session() as session:
        waiting = User(
            name="Sub", battleTag="Sub#8", discordTag="sub", discordId="8", race="HU"
        )
        session.add(waiting)
        session.commit()
        waiting_id = ident(waiting)
        session.add(
            DBUserSeasonSignup(user_id=waiting_id, season_id=seeded["season_id"])
        )
        session.commit()

    assert _expected(waiting_id) == {"gnl"}


def test_a_captain_seat_earns_the_captain_role_and_the_team_role(
    seeded: dict[str, Any],
) -> None:
    """P3 captains Alpha without playing for it, so both roles follow."""
    _bind(RoleKind.captain, "captain-role")
    _bind(RoleKind.team, "team-a", team_id=seeded["team_a_id"])
    _captain(seeded["team_a_id"], seeded["season_id"], seeded["player_ids"][2])

    assert _expected(seeded["player_ids"][2]) == {"captain-role", "team-a"}


def test_a_roster_earns_the_team_role_and_the_participant_role(
    seeded: dict[str, Any],
) -> None:
    """P1 plays for Alpha this season; P3 plays for Beta, so not Alpha's role."""
    _bind(RoleKind.team, "team-a", team_id=seeded["team_a_id"])
    _bind(RoleKind.gnl_participant, "gnl")

    assert _expected(seeded["player_ids"][0]) == {"team-a", "gnl"}
    assert _expected(seeded["player_ids"][2]) == {"gnl"}


def test_a_captain_earns_no_participant_role(seeded: dict[str, Any]) -> None:
    """The participant role is for players; a captain sitting out earns none."""
    _bind(RoleKind.gnl_participant, "gnl")
    _bind(RoleKind.captain, "captain-role")
    with Session() as session:
        outsider = User(
            name="Cap", battleTag="Cap#7", discordTag="cap", discordId="7", race="HU"
        )
        session.add(outsider)
        session.commit()
        outsider_id = outsider.id
    assert outsider_id
    _captain(seeded["team_a_id"], seeded["season_id"], outsider_id)

    assert _expected(outsider_id) == {"captain-role"}


def test_a_fantasy_captain_earns_the_fantasy_role(seeded: dict[str, Any]) -> None:
    """P1 drafted a fantasy team this season, P2 did not."""
    _bind(RoleKind.fantasy, "fantasy")

    assert _expected(seeded["player_ids"][0]) == {"fantasy"}
    assert _expected(seeded["player_ids"][1]) == set()


def test_a_champion_binding_reads_the_roster_of_the_season_it_names(
    seeded: dict[str, Any],
) -> None:
    """No column names a season winner, so the binding names the team."""
    _bind(
        RoleKind.champion,
        "champion",
        team_id=seeded["team_b_id"],
        season_id=seeded["season_id"],
    )

    assert _expected(seeded["player_ids"][2]) == {"champion"}
    assert _expected(seeded["player_ids"][0]) == set()


def test_a_binding_of_another_season_is_not_earned(seeded: dict[str, Any]) -> None:
    """The current season is the settings row, and only its bindings count."""
    with Session() as session:
        later = Season(name="Season 2", number_weeks=4, series_per_week=2)
        session.add(later)
        session.add(Settings(key="current_gnl_season", value=str(seeded["season_id"])))
        session.commit()
        later_id = later.id
    assert later_id
    _bind(RoleKind.gnl_participant, "gnl-1", season_id=seeded["season_id"])
    _bind(RoleKind.gnl_participant, "gnl-2", season_id=later_id)

    assert _expected(seeded["player_ids"][0]) == {"gnl-1"}


def test_sync_grants_what_is_missing_and_removes_only_bound_roles(
    monkeypatch: pytest.MonkeyPatch, seeded: dict[str, Any]
) -> None:
    """A role no binding names is the guild's business, not the app's."""
    _bind(RoleKind.team, "team-a", team_id=seeded["team_a_id"])
    _bind(RoleKind.captain, "captain-role")
    calls = _guild(monkeypatch, {"1": ["captain-role", "unbound-role"]})

    reports = discord_roles.sync([seeded["player_ids"][0]])

    assert [(one.missing, one.extra) for one in reports] == [
        (["team-a"], ["captain-role"])
    ]
    assert calls == [
        ("GET", f"{MEMBERS}/1"),
        ("PUT", f"{MEMBERS}/1/roles/team-a"),
        ("DELETE", f"{MEMBERS}/1/roles/captain-role"),
    ]


def test_the_report_names_every_account_the_guild_disagrees_with(
    client: Client,
    monkeypatch: pytest.MonkeyPatch,
    auth_headers: dict[str, str],
    seeded: dict[str, Any],
) -> None:
    """One row per account with a diff; an account in step is left out."""
    _bind(RoleKind.team, "team-a", team_id=seeded["team_a_id"])
    _guild(monkeypatch, {"2": ["team-a"]})

    resp = client.get("/config/discord-roles", headers=auth_headers)

    assert resp.status_code == 200, resp.text
    assert resp.json() == [
        {
            "user_id": seeded["player_ids"][0],
            "discord_id": "1",
            "name": "P1",
            "missing": ["team-a"],
            "extra": [],
        }
    ]


def test_the_report_route_admits_admins_only(
    client: Client, seeded: dict[str, Any]
) -> None:
    resp = client.get("/config/discord-roles")
    assert resp.status_code == 401
    assert resp.json() == {"error": "Missing Authorization Header"}


def test_without_a_bot_token_nothing_is_read_or_written(
    client: Client,
    monkeypatch: pytest.MonkeyPatch,
    auth_headers: dict[str, str],
    seeded: dict[str, Any],
) -> None:
    """The suite fails any call a test did not stand in for, so this proves it."""
    monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
    _bind(RoleKind.gnl_participant, "gnl")

    assert discord_roles.sync([seeded["player_ids"][0]]) == []
    resp = client.post("/config/discord-roles/sync", json={}, headers=auth_headers)
    assert resp.status_code == 200, resp.text
    assert resp.json() == []
    assert client.get("/config/discord-roles", headers=auth_headers).json() == []


def test_a_binding_is_created_read_and_deleted(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    created = client.post(
        "/config/discord-role-bindings",
        json={"kind": "team", "team_id": seeded["team_a_id"], "discord_role": "team-a"},
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    assert created.json() == {
        "id": created.json()["id"],
        "kind": "team",
        "season_id": None,
        "team_id": seeded["team_a_id"],
        "discord_role": "team-a",
    }

    updated = client.put(
        f"/config/discord-role-bindings/{created.json()['id']}",
        json={"discord_role": "team-alpha"},
        headers=auth_headers,
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["discord_role"] == "team-alpha"
    assert client.get("/config/discord-role-bindings", headers=auth_headers).json() == [
        updated.json()
    ]

    gone = client.delete(
        f"/config/discord-role-bindings/{created.json()['id']}", headers=auth_headers
    )
    assert gone.status_code == 204
    assert (
        client.get("/config/discord-role-bindings", headers=auth_headers).json() == []
    )


def test_an_unknown_binding_answers_404(
    client: Client, auth_headers: dict[str, str]
) -> None:
    resp = client.delete("/config/discord-role-bindings/404", headers=auth_headers)
    assert resp.status_code == 404
    assert resp.json() == {"error": "Discord role binding not found by id: 404"}
