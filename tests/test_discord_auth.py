"""The Discord login: the session it mints, the identity it carries, and the role that follows.

Discord is stood in for: the code exchange, the account read and the bot's
guild reads are patched per test.
"""

from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
import requests
from httpx2 import Client
from starlette.requests import Request

from app.core.db import Session
from app.core.security import SESSION_KIND, create_access_token, decode_token
from app.services import discord

ACCOUNT = {"id": "42", "username": "player", "global_name": "Player", "avatar": "abc"}

GUILD_ID = "316390574808760322"

# The guild as the bot reads it: nobody in the tests owns it or holds an admin role.
GUILD = {"id": GUILD_ID, "name": "WC3 Gym", "owner_id": "999", "roles": []}
ADMIN_ROLE = {"id": "guild-admins", "permissions": "8"}

# The member's bearer: stub_login writes the session of its account in here,
# so a test module that imported it sends that account's session.
SESSION = {"Authorization": "Bearer no-session-yet"}


# The account reads answer with one object or a list of them.
type Body = dict[str, Any] | list[dict[str, Any]]


class FakeResponse:
    def __init__(self, status_code: int, body: Body) -> None:
        self.status_code = status_code
        self.ok = status_code < 400
        self.body = body

    def json(self) -> Body:
        return self.body


def session_for(account: dict[str, Any]) -> str:
    """The session token the Discord login mints for that account."""
    return create_access_token(
        account["id"],
        60,
        SESSION_KIND,
        {
            "name": account.get("global_name") or account.get("username"),
            "avatar": account.get("avatar"),
        },
    )


def stub_login(
    monkeypatch: pytest.MonkeyPatch,
    signed_in: bool = True,
    a_member: bool = True,
    member_roles: list[str] | None = None,
    guild: dict[str, Any] | None = None,
    account: dict[str, Any] | None = None,
    calls: list[str] | None = None,
) -> None:
    """Sign the account in through SESSION, and answer the bot's guild reads.

    Every path the bot reads is appended to `calls`, so a test can assert
    that a login read the guild, or that it did not.
    """
    who = account or ACCOUNT
    guild_data = {**GUILD, **(guild or {})}

    def bot_get(path: str) -> FakeResponse:
        if calls is not None:
            calls.append(path)
        if path == f"/guilds/{GUILD_ID}":
            return FakeResponse(200, guild_data)
        assert path == f"/guilds/{GUILD_ID}/members/{who['id']}"
        if not a_member:
            return FakeResponse(404, {"message": "Unknown Member"})
        return FakeResponse(200, {"roles": member_roles or []})

    SESSION["Authorization"] = (
        f"Bearer {session_for(who)}" if signed_in else "Bearer not-a-session"
    )
    monkeypatch.setenv("DISCORD_GUILD_ID", GUILD_ID)
    monkeypatch.setenv("DISCORD_BOT_TOKEN", "a-bot-token")
    monkeypatch.setenv("ADMIN_DISCORD_IDS", "220202568490418179")
    monkeypatch.setattr(discord, "_bot_get", bot_get)


def _grant(client: Client, headers: dict[str, str], discord_id: str) -> None:
    """Make that Discord account an admin, the way the Config page does."""
    resp = client.post(
        "/config/admins", json={"discord_id": discord_id}, headers=headers
    )
    assert resp.status_code == 201, resp.text


def test_a_bearer_that_is_no_session_is_refused(
    client: Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub_login(monkeypatch, signed_in=False)
    resp = client.get("/me", headers=SESSION)
    assert resp.status_code == 401
    assert resp.json() == {"error": "Not signed in"}


def test_an_expired_session_is_refused(
    client: Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub_login(monkeypatch)
    expired = create_access_token("42", -1, SESSION_KIND, {"name": "Player"})
    resp = client.get("/me", headers={"Authorization": f"Bearer {expired}"})
    assert resp.status_code == 401


@pytest.fixture
def discord_app(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DISCORD_APPLICATION_ID", "an-app")
    monkeypatch.setenv("DISCORD_CLIENT_SECRET", "a-secret")
    monkeypatch.setenv("FRONTEND_URL", "https://app.example")


def test_the_login_starts_at_discord(client: Client, discord_app: None) -> None:
    resp = client.get("/auth/discord/start", follow_redirects=False)
    assert resp.status_code == 302
    url = urlparse(resp.headers["location"])
    query = parse_qs(url.query)
    assert f"{url.netloc}{url.path}" == "discord.com/oauth2/authorize"
    assert query["scope"] == ["identify"]
    assert query["client_id"] == ["an-app"]
    assert query["redirect_uri"][0].endswith("/auth/discord/callback")
    assert decode_token(query["state"][0])["type"] == "discord_state"


def test_the_login_is_off_without_the_client_secret(
    client: Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("DISCORD_APPLICATION_ID", "an-app")
    monkeypatch.delenv("DISCORD_CLIENT_SECRET", raising=False)
    assert client.get("/auth/discord/start").status_code == 503


def _callback(client: Client, **query: str) -> str:
    resp = client.get("/auth/discord/callback", params=query, follow_redirects=False)
    assert resp.status_code in (302, 307), resp.text
    assert resp.headers["cache-control"] == "no-store"
    return resp.headers["location"]


def test_the_callback_hands_the_frontend_a_session(
    client: Client, monkeypatch: pytest.MonkeyPatch, discord_app: None
) -> None:
    exchanged: list[str] = []

    def exchange_code(code: str, redirect_uri: str) -> str:
        exchanged.append(code)
        return "discord-token"

    monkeypatch.setattr(discord, "exchange_code", exchange_code)
    monkeypatch.setattr(discord, "identify", lambda token: ACCOUNT)
    state = create_access_token("start", 10, "discord_state")
    location = _callback(client, code="a-code", state=state)

    url = urlparse(location)
    assert (
        f"{url.scheme}://{url.netloc}{url.path}" == "https://app.example/sso-callback"
    )
    assert url.query == ""  # the token rides in the fragment, never to a server
    claims = decode_token(parse_qs(url.fragment)["token"][0])
    assert claims["type"] == SESSION_KIND
    assert (claims["sub"], claims["name"], claims["avatar"]) == ("42", "Player", "abc")
    assert "role" not in claims  # read live on every request
    assert exchanged == ["a-code"]


@pytest.mark.parametrize(
    ("query", "reason"),
    [
        ({"error": "access_denied"}, "denied"),
        ({"code": "a-code", "state": "forged"}, "state"),
        ({"code": "a-code", "state": "bnet"}, "state"),
    ],
)
def test_a_failed_callback_says_why(
    client: Client, discord_app: None, query: dict[str, str], reason: str
) -> None:
    if query.get("state") == "bnet":  # a state signed for another flow
        query = {**query, "state": create_access_token("start", 10, "bnet_state")}
    location = _callback(client, **query)
    assert location == f"https://app.example/login?login=error&reason={reason}"


def test_a_code_discord_refuses_says_token(
    client: Client, monkeypatch: pytest.MonkeyPatch, discord_app: None
) -> None:
    def refuse(code: str, redirect_uri: str) -> str:
        raise requests.HTTPError("400 invalid_grant")

    monkeypatch.setattr(discord, "exchange_code", refuse)
    state = create_access_token("start", 10, "discord_state")
    location = _callback(client, code="old-code", state=state)
    assert location == "https://app.example/login?login=error&reason=token"


def test_a_member_reads_me(client: Client, monkeypatch: pytest.MonkeyPatch) -> None:
    stub_login(monkeypatch)
    resp = client.get("/me", headers=SESSION)
    assert resp.status_code == 200
    assert resp.json() == {
        "discord_id": "42",
        "name": "Player",
        "avatar": "https://cdn.discordapp.com/avatars/42/abc.png",
        "role": "member",
        "actual_role": "member",
        "user": None,
        "superadmin": False,
        "organizer": False,
        "organizer_request": None,
        "signed_up": False,
        "season_id": None,
        "team": None,
        "seats": [],
        "seasons": [],
    }


def test_a_double_guard_resolves_the_claims_once(
    client: Client, monkeypatch: pytest.MonkeyPatch, seeded: dict[str, Any]
) -> None:
    """The veto read guards twice, so its claims are resolved once per request.

    The board is polled every few seconds while two players trade picks, and
    Discord rate limit is a standing constraint.
    """
    calls: list[str] = []
    stub_login(monkeypatch, account={**ACCOUNT, "id": "1"}, calls=calls)
    resp = client.get(
        f"/player-series/{seeded['series_played_id']}/veto", headers=SESSION
    )
    assert resp.status_code == 200, resp.text
    assert calls.count(f"/guilds/{GUILD_ID}/members/1") == 1


def test_me_carries_the_linked_user(
    client: Client, monkeypatch: pytest.MonkeyPatch, seeded: dict[str, Any]
) -> None:
    stub_login(monkeypatch, account={**ACCOUNT, "id": "1"})
    resp = client.get("/me", headers=SESSION)
    assert resp.status_code == 200
    assert resp.json()["user"]["battleTag"] == "P1#1111"


def test_an_account_outside_the_guild_logs_in_as_a_guest(
    client: Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A guest reads the public pages; the login itself is not refused."""
    stub_login(monkeypatch, a_member=False)
    resp = client.get("/me", headers=SESSION)
    assert resp.status_code == 200
    assert resp.json()["role"] == "guest"


def test_the_allowlist_makes_an_admin_without_a_guild_read(
    client: Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The environment answers, so the login asks Discord nothing."""
    calls: list[str] = []
    stub_login(
        monkeypatch, account={**ACCOUNT, "id": "220202568490418179"}, calls=calls
    )
    resp = client.get("/me", headers=SESSION)
    assert resp.json()["role"] == "admin"
    assert calls == []


def test_a_grant_makes_an_admin(
    client: Client, monkeypatch: pytest.MonkeyPatch, auth_headers: dict[str, str]
) -> None:
    _grant(client, auth_headers, ACCOUNT["id"])
    stub_login(monkeypatch)
    assert client.get("/me", headers=SESSION).json()["role"] == "admin"


def test_a_granted_account_outside_the_guild_is_an_admin(
    client: Client, monkeypatch: pytest.MonkeyPatch, auth_headers: dict[str, str]
) -> None:
    """The grant is the app's, so guild membership decides nothing for it."""
    _grant(client, auth_headers, ACCOUNT["id"])
    stub_login(monkeypatch, a_member=False)
    assert client.get("/me", headers=SESSION).json()["role"] == "admin"


def test_a_member_session_is_no_admin_token(
    client: Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub_login(monkeypatch)
    resp = client.get("/config/koth/nightbot-token", headers=SESSION)
    assert resp.status_code == 403
    assert resp.json() == {"error": "Admins only"}


def test_view_as_lowers_an_admin_for_the_request(
    client: Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The header rewrites the role where the guards read it, so the 403 is real."""
    stub_login(monkeypatch, account={**ACCOUNT, "id": "220202568490418179"})
    viewing = SESSION | {"X-View-As": "member"}
    me = client.get("/me", headers=viewing).json()
    assert me["role"] == "member"
    assert me["actual_role"] == "admin"
    resp = client.get("/config/koth/nightbot-token", headers=viewing)
    assert resp.status_code == 403
    # without the header the same session is the admin again
    assert client.get("/me", headers=SESSION).json()["role"] == "admin"


def test_view_as_captain_names_the_chosen_team(
    client: Client, monkeypatch: pytest.MonkeyPatch, seeded: dict[str, Any]
) -> None:
    stub_login(monkeypatch, account={**ACCOUNT, "id": "220202568490418179"})
    viewing = SESSION | {
        "X-View-As": "captain",
        "X-View-Team": str(seeded["team_a_id"]),
    }
    me = client.get("/me", headers=viewing).json()
    assert me["role"] == "captain"
    assert me["team"]["id"] == seeded["team_a_id"]
    # the older header stands for one seat, so a seat-guarded route admits it
    guarded = client.get(
        f"/events/{seeded['season_id']}/teams/{seeded['team_a_id']}/availability",
        headers=viewing,
    )
    assert guarded.status_code == 200, guarded.text


def test_view_as_is_ignored_for_a_member(
    client: Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub_login(monkeypatch)
    me = client.get("/me", headers=SESSION | {"X-View-As": "guest"}).json()
    assert me["role"] == "member"
    assert me["actual_role"] == "member"


def test_view_as_ignores_a_nonsense_role(
    client: Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    """admin is not a target either: the header only lowers, never restores."""
    stub_login(monkeypatch, account={**ACCOUNT, "id": "220202568490418179"})
    me = client.get("/me", headers=SESSION | {"X-View-As": "superuser"}).json()
    assert me["role"] == "admin"


def _login() -> dict[str, Any]:
    """The claims a Discord session resolves to, read without a route."""
    from fastapi.security import HTTPAuthorizationCredentials

    from app.api.deps import require_login

    request = Request({"type": "http", "headers": []})
    credentials = HTTPAuthorizationCredentials(
        scheme="Bearer", credentials=SESSION["Authorization"].removeprefix("Bearer ")
    )
    return require_login(request, credentials)


def _bind_captain_role(client: Client, headers: dict[str, str]) -> None:
    """Bind role-1 to the captain seat and sync it, the way the config page does."""
    resp = client.post(
        "/config/discord-role-bindings",
        json={"kind": "captain", "discord_role": "role-1", "synced": True},
        headers=headers,
    )
    assert resp.status_code == 201, resp.json()


def _set_captains(
    client: Client, headers: dict[str, str], team_id: int, captain_ids: list[int]
) -> dict[str, Any]:
    resp = client.put(
        f"/events/1/teams/{team_id}/captains",
        json={"captain_ids": captain_ids},
        headers=headers,
    )
    assert resp.status_code == 200, resp.json()
    return dict(resp.json())


def test_a_captain_slot_makes_a_captain(
    client: Client,
    monkeypatch: pytest.MonkeyPatch,
    seeded: dict[str, Any],
    auth_headers: dict[str, str],
) -> None:
    """P1 captains Alpha this season, so the claims name the team."""
    monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
    _set_captains(client, auth_headers, seeded["team_a_id"], [seeded["player_ids"][0]])

    stub_login(monkeypatch, account={**ACCOUNT, "id": "1"})
    claims = _login()
    assert claims["role"] == "captain"
    assert claims["team_id"] == seeded["team_a_id"]
    assert claims["season_id"] == seeded["season_id"]
    me = client.get("/me", headers=SESSION).json()
    assert me["role"] == "captain"
    assert me["team"]["id"] == seeded["team_a_id"]


def test_a_captain_slot_in_no_season_of_this_account_is_no_captain(
    client: Client,
    monkeypatch: pytest.MonkeyPatch,
    seeded: dict[str, Any],
    auth_headers: dict[str, str],
) -> None:
    """P1 captains, so P2 does not."""
    monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
    _set_captains(client, auth_headers, seeded["team_a_id"], [seeded["player_ids"][0]])

    stub_login(monkeypatch, account={**ACCOUNT, "id": "2"})
    assert client.get("/me", headers=SESSION).json()["role"] == "member"


def test_require_captain_refuses_a_member(
    client: Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    from fastapi.security import HTTPAuthorizationCredentials

    from app.api.deps import require_captain
    from app.core.exceptions import ApiError

    stub_login(monkeypatch)
    request = Request({"type": "http", "headers": []})
    credentials = HTTPAuthorizationCredentials(
        scheme="Bearer", credentials=SESSION["Authorization"].removeprefix("Bearer ")
    )

    with pytest.raises(ApiError) as refused:
        require_captain(request, credentials)

    assert refused.value.status_code == 403
    assert refused.value.body == {"error": "Captains only"}


def test_require_captain_admits_an_admin(
    client: Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    from fastapi.security import HTTPAuthorizationCredentials

    from app.api.deps import require_captain

    stub_login(monkeypatch, account={**ACCOUNT, "id": "220202568490418179"})
    request = Request({"type": "http", "headers": []})
    credentials = HTTPAuthorizationCredentials(
        scheme="Bearer", credentials=SESSION["Authorization"].removeprefix("Bearer ")
    )

    assert require_captain(request, credentials)["role"] == "admin"


def test_saving_captains_writes_the_guild_role(
    client: Client,
    monkeypatch: pytest.MonkeyPatch,
    seeded: dict[str, Any],
    auth_headers: dict[str, str],
) -> None:
    """The new captain is granted the bound role, the old one loses it."""
    _bind_captain_role(client, auth_headers)
    monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
    _set_captains(client, auth_headers, seeded["team_a_id"], [seeded["player_ids"][0]])

    calls: list[tuple[str, str]] = []
    members = f"{discord.API_URL}/guilds/{GUILD_ID}/members"

    def request(method: str, url: str, **kwargs: object) -> FakeResponse:
        calls.append((method, url))
        # Only the captain of yesterday holds the role in the guild
        return FakeResponse(200, {"roles": ["role-1"] if url == f"{members}/1" else []})

    monkeypatch.setenv("DISCORD_BOT_TOKEN", "a-bot-token")
    monkeypatch.setenv("DISCORD_GUILD_ID", GUILD_ID)
    monkeypatch.setattr(discord._session, "request", request)
    team = _set_captains(
        client, auth_headers, seeded["team_a_id"], [seeded["player_ids"][1]]
    )

    assert calls == [
        ("GET", f"{members}/1"),
        ("GET", f"{members}/2"),
        ("DELETE", f"{members}/1/roles/role-1"),
        ("PUT", f"{members}/2/roles/role-1"),
        ("GET", f"{members}/2"),
    ]
    # The guild answered without the role, so the page can show the chip
    assert team["discord_role_missing"] == ["2"]


def test_saving_captains_without_a_bot_token_calls_nothing(
    client: Client,
    monkeypatch: pytest.MonkeyPatch,
    seeded: dict[str, Any],
    auth_headers: dict[str, str],
) -> None:
    """No bot token, no call: the suite fails any request it did not stand in for."""
    monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
    team = _set_captains(
        client, auth_headers, seeded["team_a_id"], [seeded["player_ids"][0]]
    )
    assert team["discord_role_missing"] == []


def test_me_names_the_team_a_member_rosters_for(
    client: Client, monkeypatch: pytest.MonkeyPatch, seeded: dict[str, Any]
) -> None:
    """The nav links a member to his team, so /me names it for any role."""
    from app.models.settings import Settings
    from tests.test_player_session import member_session

    with Session.begin() as session:
        session.add(Settings(key="current_gnl_season", value=str(seeded["season_id"])))

    headers = member_session(monkeypatch, discord_id="1")
    body = client.get("/me", headers=headers).json()

    assert body["team"] == {"id": seeded["team_a_id"], "name": "Alpha"}
