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
from app.models.enums import RoleKind, RoleScope
from app.models.relationships import DBTeamSeasonCaptain, DBUserSeasonSignup
from app.models.season import Season
from app.models.user import User
from app.models.user_team_season import DBUserTeamSeason
from app.services import discord, discord_roles
from tests.test_discord_auth import GUILD_ID, FakeResponse

MEMBERS = f"{discord.API_URL}/guilds/{GUILD_ID}/members"

# The guild list the bot reads: it holds bot-role, so only what sits under it is its to grant.
ROLES = [
    {"id": GUILD_ID, "name": "@everyone", "position": 0, "color": 0},
    {"id": "team-a", "name": "Team A", "position": 2, "color": 5793266},
    {"id": "bot-role", "name": "The Bot", "position": 5, "color": 0, "managed": True},
    {"id": "above-the-bot", "name": "Above", "position": 9, "color": 0},
]


def _bind(
    kind: RoleKind, role: str, synced: bool = True, **columns: int | RoleScope
) -> int:
    with Session() as session:
        binding = DiscordRoleBinding(
            kind=kind, discord_role=role, synced=synced, **columns
        )
        session.add(binding)
        session.commit()
        return ident(binding)


def _expected(user_id: int) -> set[str]:
    with Session() as session:
        user = session.get(User, user_id)
        assert user
        return discord_roles.expected_roles_of([user], session)[ident(user)]


def _captain(team_id: int, season_id: int, user_id: int) -> None:
    with Session() as session:
        session.add(
            DBTeamSeasonCaptain(team_id=team_id, season_id=season_id, user_id=user_id)
        )
        session.commit()


def _later_season() -> int:
    """A second season, which the roles follow as the current one."""
    with Session() as session:
        later = Season(name="Season 2", number_weeks=4, series_per_week=2)
        session.add(later)
        session.commit()
        return ident(later)


def _guild(
    monkeypatch: pytest.MonkeyPatch, roles: dict[str, list[str]]
) -> list[tuple[str, str]]:
    """Answer the member reads with those roles and record every call."""
    calls: list[tuple[str, str]] = []

    def request(method: str, url: str, **kwargs: object) -> FakeResponse:
        calls.append((method, url))
        if url.startswith(f"{MEMBERS}?"):
            return FakeResponse(
                200, [{"user": {"id": id}, "roles": held} for id, held in roles.items()]
            )
        if url == f"{discord.API_URL}/users/@me":
            return FakeResponse(200, {"id": "bot"})
        if url == f"{MEMBERS}/bot":
            return FakeResponse(200, {"roles": ["bot-role"]})
        if url.endswith("/roles"):
            return FakeResponse(200, ROLES)
        return FakeResponse(200, {"roles": roles.get(url.rsplit("/", 1)[-1], [])})

    monkeypatch.setenv("DISCORD_BOT_TOKEN", "a-bot-token")
    monkeypatch.setenv("DISCORD_GUILD_ID", GUILD_ID)
    monkeypatch.setattr(discord.requests, "request", request)
    return calls


def test_an_admin_binding_is_never_synced(
    monkeypatch: pytest.MonkeyPatch, seeded: dict[str, Any]
) -> None:
    """The admin role is hand-managed: a grant earns nothing, a held role stays."""
    _bind(RoleKind.admin, "admin-role")
    with Session() as session:
        session.add(AdminGrant(discord_id="1", granted_by="admin"))
        session.commit()

    assert _expected(seeded["player_ids"][0]) == set()
    calls = _guild(monkeypatch, {"2": ["admin-role"]})
    assert discord_roles.sync([seeded["player_ids"][1]]) == []
    assert calls == [("GET", f"{MEMBERS}/2")]


def test_granting_an_admin_writes_no_guild_role(
    client: Client,
    monkeypatch: pytest.MonkeyPatch,
    auth_headers: dict[str, str],
    seeded: dict[str, Any],
) -> None:
    """The grant takes its name from the users row and leaves the guild alone."""
    _bind(RoleKind.admin, "admin-role")
    calls = _guild(monkeypatch, {})

    resp = client.post("/config/admins", json={"discord_id": "1"}, headers=auth_headers)

    assert resp.status_code == 201, resp.text
    assert resp.json()["name"] == "P1"
    assert calls == []


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


def test_a_champion_binding_crowns_the_seasons_standings_winner(
    seeded: dict[str, Any],
) -> None:
    """Alpha won the seeded season 2-1, so its roster earns the role."""
    _bind(
        RoleKind.champion,
        "champion",
        scope=RoleScope.season,
        season_id=seeded["season_id"],
    )

    assert _expected(seeded["player_ids"][0]) == {"champion"}
    assert _expected(seeded["player_ids"][2]) == set()


def test_a_season_binding_outlives_its_season(seeded: dict[str, Any]) -> None:
    """Season 2 is current, but P1's season 1 roles are kept, not stripped."""
    later_id = _later_season()
    one = RoleScope.season
    _bind(RoleKind.gnl_participant, "gnl-1", scope=one, season_id=seeded["season_id"])
    _bind(RoleKind.gnl_participant, "gnl-2", scope=one, season_id=later_id)
    _bind(RoleKind.fantasy, "fantasy-1", scope=one, season_id=seeded["season_id"])
    _bind(RoleKind.champion, "champion-1", scope=one, season_id=seeded["season_id"])
    _bind(RoleKind.team, "team-a", team_id=seeded["team_a_id"])

    # P1 played, drafted and won in season 1; the team role reads the current season
    assert _expected(seeded["player_ids"][0]) == {"gnl-1", "fantasy-1", "champion-1"}


def test_a_captain_binding_scoped_to_every_season_reads_an_old_seat(
    seeded: dict[str, Any],
) -> None:
    """P3 captained Alpha in season 1; only the all scope still earns it in season 2."""
    _captain(seeded["team_a_id"], seeded["season_id"], seeded["player_ids"][2])
    _later_season()
    _bind(RoleKind.captain, "captain-now")
    _bind(RoleKind.captain, "captain-ever", scope=RoleScope.all)

    assert _expected(seeded["player_ids"][2]) == {"captain-ever"}


def test_a_team_binding_scoped_to_every_season_reads_an_old_roster(
    seeded: dict[str, Any],
) -> None:
    """P1 played for Alpha in season 1 and P3 for Beta, so only P1 earns Alpha's role."""
    _later_season()
    _bind(RoleKind.team, "team-a-now", team_id=seeded["team_a_id"])
    _bind(
        RoleKind.team, "team-a-ever", scope=RoleScope.all, team_id=seeded["team_a_id"]
    )

    assert _expected(seeded["player_ids"][0]) == {"team-a-ever"}
    assert _expected(seeded["player_ids"][2]) == set()


def test_participant_and_fantasy_scoped_to_every_season_read_an_old_season(
    seeded: dict[str, Any],
) -> None:
    """P1 played and drafted in season 1; P2 only played, so no fantasy role."""
    _later_season()
    _bind(RoleKind.gnl_participant, "gnl-ever", scope=RoleScope.all)
    _bind(RoleKind.fantasy, "fantasy-ever", scope=RoleScope.all)
    _bind(RoleKind.gnl_participant, "gnl-now")

    assert _expected(seeded["player_ids"][0]) == {"gnl-ever", "fantasy-ever"}
    assert _expected(seeded["player_ids"][1]) == {"gnl-ever"}


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


def test_a_full_report_reads_the_guild_once(
    monkeypatch: pytest.MonkeyPatch, seeded: dict[str, Any]
) -> None:
    """Six or more accounts list the guild instead of reading each member."""
    _bind(RoleKind.team, "team-a", team_id=seeded["team_a_id"])
    with Session() as session:
        for n in range(6):
            session.add(
                User(
                    name=f"U{n}",
                    battleTag=f"U{n}#1",
                    discordTag=f"u{n}",
                    discordId=f"9{n}",
                    race="HU",
                )
            )
        session.commit()
    calls = _guild(monkeypatch, {"1": ["team-a"], "2": [], "90": ["team-a"]})

    reports = discord_roles.report()

    assert calls == [("GET", f"{MEMBERS}?limit=1000&after=0")]
    assert [(one.discord_id, one.missing, one.extra) for one in reports] == [
        ("2", ["team-a"], []),
        ("90", [], ["team-a"]),
    ]


def test_the_guild_roles_route_lists_the_guild_top_first(
    client: Client,
    monkeypatch: pytest.MonkeyPatch,
    auth_headers: dict[str, str],
) -> None:
    """A role above the bot cannot be managed, and @everyone is not a role to bind."""
    _guild(monkeypatch, {"1": ["team-a"], "2": ["team-a", "above-the-bot"]})

    resp = client.get("/config/discord-guild-roles", headers=auth_headers)

    assert resp.status_code == 200, resp.text
    assert resp.json() == [
        {
            "id": "above-the-bot",
            "name": "Above",
            "color": None,
            "position": 9,
            "members": 1,
            "manageable": False,
        },
        {
            "id": "bot-role",
            "name": "The Bot",
            "color": None,
            "position": 5,
            "members": 0,
            "manageable": False,
        },
        {
            "id": "team-a",
            "name": "Team A",
            "color": "#5865f2",
            "position": 2,
            "members": 2,
            "manageable": True,
        },
    ]


def test_a_binding_to_a_role_above_the_bot_answers_400(
    client: Client,
    monkeypatch: pytest.MonkeyPatch,
    auth_headers: dict[str, str],
    seeded: dict[str, Any],
) -> None:
    """The bot could never grant it, so the binding is refused at the write."""
    _guild(monkeypatch, {})

    resp = client.post(
        "/config/discord-role-bindings",
        json={"kind": "captain", "discord_role": "above-the-bot"},
        headers=auth_headers,
    )

    assert resp.status_code == 400, resp.text
    assert resp.json() == {
        "error": "The bot cannot manage that role: it sits above the bot in Discord"
    }


def test_an_unsynced_binding_is_left_to_the_guild(
    monkeypatch: pytest.MonkeyPatch, seeded: dict[str, Any]
) -> None:
    """P1 earns the team role, but nobody asked the app to manage it."""
    _bind(RoleKind.team, "team-a", synced=False, team_id=seeded["team_a_id"])
    calls = _guild(monkeypatch, {"1": []})

    assert discord_roles.report([seeded["player_ids"][0]]) == []
    assert discord_roles.sync([seeded["player_ids"][0]]) == []
    assert calls == [("GET", f"{MEMBERS}/1"), ("GET", f"{MEMBERS}/1")]


def test_a_new_binding_starts_unsynced_until_an_admin_says_so(
    client: Client,
    monkeypatch: pytest.MonkeyPatch,
    auth_headers: dict[str, str],
    seeded: dict[str, Any],
) -> None:
    """The page creates the binding first and turns the sync on after."""
    created = client.post(
        "/config/discord-role-bindings",
        json={"kind": "team", "team_id": seeded["team_a_id"], "discord_role": "team-a"},
        headers=auth_headers,
    )
    assert created.status_code == 201, created.text
    assert created.json()["synced"] is False

    updated = client.put(
        f"/config/discord-role-bindings/{created.json()['id']}",
        json={"synced": True},
        headers=auth_headers,
    )
    assert updated.status_code == 200, updated.text
    assert updated.json()["synced"] is True

    calls = _guild(monkeypatch, {"1": []})
    assert [one.missing for one in discord_roles.sync([seeded["player_ids"][0]])] == [
        ["team-a"]
    ]
    assert calls == [("GET", f"{MEMBERS}/1"), ("PUT", f"{MEMBERS}/1/roles/team-a")]


def test_an_admin_binding_cannot_be_marked_synced(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    """The admin role stays hand-managed however the page asks."""
    binding_id = _bind(RoleKind.admin, "admin-role", synced=False)

    resp = client.put(
        f"/config/discord-role-bindings/{binding_id}",
        json={"synced": True},
        headers=auth_headers,
    )

    assert resp.status_code == 400, resp.text
    assert resp.json() == {
        "error": "Admin roles are hand-managed in Discord, not synced"
    }


def test_a_sync_of_named_roles_leaves_every_other_binding_alone(
    monkeypatch: pytest.MonkeyPatch, seeded: dict[str, Any]
) -> None:
    """P1 earns the team role and holds the captain role; only the team role is asked for."""
    _bind(RoleKind.team, "team-a", team_id=seeded["team_a_id"])
    _bind(RoleKind.captain, "captain-role")
    calls = _guild(monkeypatch, {"1": ["captain-role"]})

    reports = discord_roles.sync([seeded["player_ids"][0]], ["team-a"])

    assert [(one.missing, one.extra) for one in reports] == [(["team-a"], [])]
    assert calls == [("GET", f"{MEMBERS}/1"), ("PUT", f"{MEMBERS}/1/roles/team-a")]


def test_the_role_groups_route_counts_who_earns_each_group(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    """The seeded league: four players, one bettor, Alpha champion, no captain seat."""
    resp = client.get("/config/discord-role-groups", headers=auth_headers)

    assert resp.status_code == 200, resp.text
    assert resp.json() == [
        {
            "kind": "captain",
            "scope": "current",
            "season_id": None,
            "team_id": None,
            "label": "Captains",
            "count": 0,
        },
        {
            "kind": "gnl_participant",
            "scope": "current",
            "season_id": None,
            "team_id": None,
            "label": "Players",
            "count": 4,
        },
        {
            "kind": "fantasy",
            "scope": "current",
            "season_id": None,
            "team_id": None,
            "label": "Bettors",
            "count": 1,
        },
        {
            "kind": "champion",
            "scope": "season",
            "season_id": seeded["season_id"],
            "team_id": None,
            "label": "Champions",
            "count": 2,
        },
        {
            "kind": "team",
            "scope": "current",
            "season_id": None,
            "team_id": seeded["team_a_id"],
            "label": "Alpha",
            "count": 2,
        },
        {
            "kind": "team",
            "scope": "current",
            "season_id": None,
            "team_id": seeded["team_b_id"],
            "label": "Beta",
            "count": 2,
        },
    ]


def test_the_role_groups_route_counts_every_season_for_the_all_scope(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    """Season 2 adds a seat and a roster row, and the all scope counts both seasons."""
    later_id = _later_season()
    _captain(seeded["team_a_id"], later_id, seeded["player_ids"][2])
    with Session() as session:
        session.add(
            DBUserTeamSeason(
                user_id=seeded["player_ids"][0],
                team_id=seeded["team_b_id"],
                season_id=later_id,
            )
        )
        session.commit()

    resp = client.get(
        f"/config/discord-role-groups?scope=all&season_id={seeded['season_id']}",
        headers=auth_headers,
    )

    assert resp.status_code == 200, resp.text
    assert [
        (one["kind"], one["scope"], one["season_id"], one["label"], one["count"])
        for one in resp.json()
    ] == [
        ("captain", "all", None, "Captains", 1),
        ("gnl_participant", "all", None, "Players", 4),
        ("fantasy", "all", None, "Bettors", 1),
        ("champion", "season", seeded["season_id"], "Champions", 2),
        ("team", "all", None, "Alpha", 3),
        ("team", "all", None, "Beta", 3),
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
        "scope": "current",
        "season_id": None,
        "team_id": seeded["team_a_id"],
        "discord_role": "team-a",
        "synced": False,
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


@pytest.mark.parametrize(
    ("body", "error"),
    [
        (
            {"kind": "admin", "discord_role": "a"},
            "Admin roles are hand-managed in Discord, not synced",
        ),
        ({"kind": "team", "discord_role": "a"}, "A team binding needs the team"),
        (
            {"kind": "champion", "discord_role": "a"},
            "A champion binding crowns one season",
        ),
        (
            {
                "kind": "champion",
                "discord_role": "a",
                "scope": "season",
                "season_id": 1,
                "team_id": 1,
            },
            "The champion team is derived from the standings",
        ),
        (
            {"kind": "gnl_participant", "discord_role": "a", "scope": "season"},
            "A season binding needs the season it follows",
        ),
    ],
)
def test_a_binding_nobody_could_earn_answers_400(
    client: Client,
    auth_headers: dict[str, str],
    seeded: dict[str, Any],
    body: dict[str, Any],
    error: str,
) -> None:
    resp = client.post("/config/discord-role-bindings", json=body, headers=auth_headers)
    assert resp.status_code == 400, resp.text
    assert error in resp.json()["error"]


def test_the_binding_list_names_the_derived_champion(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    """The winner is not stored, but the list carries it for the page."""
    _bind(
        RoleKind.champion,
        "champion",
        scope=RoleScope.season,
        season_id=seeded["season_id"],
    )

    rows = client.get("/config/discord-role-bindings", headers=auth_headers).json()
    assert [(row["kind"], row["team_id"]) for row in rows] == [
        ("champion", seeded["team_a_id"])
    ]
