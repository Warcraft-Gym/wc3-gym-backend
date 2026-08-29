"""The Clerk login: the Discord identity it resolves, and the role that follows.

Clerk and Discord are stood in for: the session check, the account's Discord
OAuth token and the reads that token makes are patched per test.
"""

from types import SimpleNamespace
from typing import Any

import pytest
from clerk_backend_api import Clerk
from clerk_backend_api.security.types import AuthStatus, RequestState
from clerk_backend_api.users import Users
from httpx2 import Client
from starlette.requests import Request

from app.services import discord

CLERK_USER_ID = "user_2abcdefghijklmnop"

ACCOUNT = {"id": "42", "username": "player", "global_name": "Player", "avatar": "abc"}

GUILD_ID = "316390574808760322"

# The guild as /users/@me/guilds lists it for a plain member.
GUILD = {"id": GUILD_ID, "name": "WC3 Gym", "owner": False, "permissions": "0"}

SESSION = {"Authorization": "Bearer a-clerk-session-token"}


# The account reads answer with one object or a list of them.
type Body = dict[str, Any] | list[dict[str, Any]]


class FakeResponse:
    def __init__(self, status_code: int, body: Body) -> None:
        self.status_code = status_code
        self.ok = status_code < 400
        self.body = body

    def json(self) -> Body:
        return self.body


def stub_clerk(
    monkeypatch: pytest.MonkeyPatch,
    signed_in: bool = True,
    linked: bool = True,
    a_member: bool = True,
    member_roles: list[str] | None = None,
    guild: dict[str, Any] | None = None,
    account: dict[str, Any] | None = None,
) -> None:
    """Answer the Clerk session check and the two calls the account's token makes."""
    guilds = [{"id": "1", "owner": True, "permissions": "8"}]
    if a_member:
        guilds.append({**GUILD, **(guild or {})})
    who = account or ACCOUNT

    def authenticate_request(
        self: Clerk, request: object, options: object
    ) -> RequestState:
        if not signed_in:
            return RequestState(status=AuthStatus.SIGNED_OUT)
        return RequestState(
            status=AuthStatus.SIGNED_IN, payload={"sub": CLERK_USER_ID, "sid": "sess_1"}
        )

    def oauth_token(self: Users, **kwargs: str) -> list[SimpleNamespace]:
        assert kwargs == {"user_id": CLERK_USER_ID, "provider": "oauth_discord"}
        if not linked:
            return []
        return [SimpleNamespace(token="discord-token", provider_user_id=who["id"])]

    def user_get(access_token: str, path: str) -> FakeResponse:
        if path == "/users/@me":
            return FakeResponse(200, who)
        if path == "/users/@me/guilds":
            return FakeResponse(200, guilds)
        return FakeResponse(200, {"roles": member_roles or []})

    monkeypatch.setenv("DISCORD_GUILD_ID", GUILD_ID)
    monkeypatch.setenv("ADMIN_DISCORD_IDS", "220202568490418179")
    monkeypatch.setattr(Clerk, "authenticate_request", authenticate_request)
    monkeypatch.setattr(Users, "get_o_auth_access_token", oauth_token)
    monkeypatch.setattr(discord, "_user_get", user_get)


def test_a_request_without_a_bearer_is_refused(client: Client) -> None:
    resp = client.get("/me")
    assert resp.status_code == 401
    assert resp.json() == {"error": "Missing Authorization Header"}


def test_a_bearer_no_clerk_session_backs_is_refused(
    client: Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub_clerk(monkeypatch, signed_in=False)
    resp = client.get("/me", headers=SESSION)
    assert resp.status_code == 401
    assert "error" in resp.json()


def test_a_login_with_no_discord_account_is_refused(
    client: Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub_clerk(monkeypatch, linked=False)
    resp = client.get("/me", headers=SESSION)
    assert resp.status_code == 401
    assert resp.json() == {"error": "No Discord account on this login"}


def test_a_member_reads_me(client: Client, monkeypatch: pytest.MonkeyPatch) -> None:
    stub_clerk(monkeypatch)
    resp = client.get("/me", headers=SESSION)
    assert resp.status_code == 200
    assert resp.json() == {
        "discord_id": "42",
        "name": "Player",
        "avatar": "https://cdn.discordapp.com/avatars/42/abc.png",
        "role": "member",
        "user": None,
    }


def test_me_carries_the_linked_user(
    client: Client, monkeypatch: pytest.MonkeyPatch, seeded: dict[str, Any]
) -> None:
    stub_clerk(monkeypatch, account={**ACCOUNT, "id": "1"})
    resp = client.get("/me", headers=SESSION)
    assert resp.status_code == 200
    assert resp.json()["user"]["battleTag"] == "P1#1111"


def test_an_account_outside_the_guild_logs_in_as_a_guest(
    client: Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A guest reads the public pages; the login itself is not refused."""
    stub_clerk(monkeypatch, a_member=False)
    resp = client.get("/me", headers=SESSION)
    assert resp.status_code == 200
    assert resp.json()["role"] == "guest"


def test_a_guest_passes_no_player_route(
    client: Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    """require_member guards the routes that read a player's own data."""
    from fastapi.security import HTTPAuthorizationCredentials

    from app.api.deps import require_member
    from app.core.exceptions import ApiError

    stub_clerk(monkeypatch, a_member=False)
    request = Request({"type": "http", "headers": []})
    credentials = HTTPAuthorizationCredentials(scheme="Bearer", credentials="a-token")

    with pytest.raises(ApiError) as refused:
        require_member(request, credentials)

    assert refused.value.status_code == 403
    assert refused.value.body == {
        "error": "No valid WC3 Gym server membership found for user"
    }


def test_the_allowlist_makes_an_admin(
    client: Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub_clerk(monkeypatch, account={**ACCOUNT, "id": "220202568490418179"})
    resp = client.get("/me", headers=SESSION)
    assert resp.json()["role"] == "admin"


def test_the_guild_owner_is_an_admin(
    client: Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub_clerk(monkeypatch, guild={"owner": True})
    resp = client.get("/me", headers=SESSION)
    assert resp.json()["role"] == "admin"


def test_an_administrator_role_makes_an_admin(
    client: Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub_clerk(monkeypatch, guild={"permissions": "8"})
    resp = client.get("/me", headers=SESSION)
    assert resp.json()["role"] == "admin"


def test_the_admin_role_setting_makes_an_admin(
    client: Client, monkeypatch: pytest.MonkeyPatch, auth_headers: dict[str, str]
) -> None:
    resp = client.put(
        "/config/settings/admin_role",
        json={"value": "gym-admins"},
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.json()
    stub_clerk(monkeypatch, member_roles=["gym-admins"])
    resp = client.get("/me", headers=SESSION)
    assert resp.json()["role"] == "admin"


def test_a_member_session_is_no_admin_token(
    client: Client, monkeypatch: pytest.MonkeyPatch
) -> None:
    stub_clerk(monkeypatch)
    resp = client.get("/config/koth/nightbot-token", headers=SESSION)
    assert resp.status_code == 403
    assert resp.json() == {"error": "Admins only"}


def test_the_admin_token_login_still_admits(
    client: Client, seeded: dict[str, Any], auth_headers: dict[str, str]
) -> None:
    """The admin token reaches an admin route without touching Clerk."""
    resp = client.get("/config/koth/nightbot-token", headers=auth_headers)
    assert resp.status_code == 200
    resp = client.get("/me", headers=auth_headers)
    assert resp.status_code == 200
    assert resp.json()["role"] == "admin"
