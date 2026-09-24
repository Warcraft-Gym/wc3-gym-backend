"""The Battle.net link: the start URL, and the callback that records the
Blizzard account on its tag and sends the browser back to the profile page.

The two Blizzard calls are stood in for; no test reaches Blizzard.
"""

from collections.abc import Callable
from typing import Any
from urllib.parse import parse_qs, urlparse

import pytest
import requests
from httpx2 import Client
from sqlalchemy import select
from sqlmodel import col

from app.api.routes import battlenet
from app.core.db import Session
from app.core.security import create_access_token, decode_token
from app.models.user_battle_tag import UserBattleTag
from tests.test_tag_routes import no_login_person

FRONT = "http://front.test"


@pytest.fixture
def bnet_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("BNET_CLIENT_ID", "client-1")
    monkeypatch.setenv("BNET_CLIENT_SECRET", "secret-1")
    monkeypatch.setenv("FRONTEND_URL", FRONT)


@pytest.fixture
def blizzard(monkeypatch: pytest.MonkeyPatch) -> Callable[[str, str], None]:
    """Blizzard answers the code with an account id and a battle tag."""

    def answer(sub: str, battletag: str) -> None:
        monkeypatch.setattr(battlenet, "_exchange_code", lambda code, uri: "tok")
        monkeypatch.setattr(
            battlenet, "_userinfo", lambda token: {"sub": sub, "battletag": battletag}
        )

    return answer


def callback(client: Client, discord_id: str = "1", **params: str) -> str:
    state = create_access_token(discord_id, 10, "bnet_state")
    resp = client.get(
        "/auth/battlenet/callback", params={"code": "c", "state": state} | params
    )
    assert resp.status_code in (302, 307), resp.text
    return resp.headers["location"]


def rows_of(user_id: int) -> list[tuple[str, str, bool, str | None]]:
    with Session() as session:
        rows = session.scalars(
            select(UserBattleTag)
            .where(col(UserBattleTag.user_id) == user_id)
            .order_by(col(UserBattleTag.id))
        ).all()
        return [(r.tag, r.source, r.is_active, r.bnet_account_id) for r in rows]


LINKED = f"{FRONT}/profile?bnet=linked"


def error(reason: str) -> str:
    return f"{FRONT}/profile?bnet=error&reason={reason}"


# GET /users/me/bnet/start


def test_start_answers_the_authorize_url_with_a_signed_state(
    client: Client,
    seeded: dict[str, Any],
    bnet_env: None,
    member: Callable[..., dict[str, str]],
) -> None:
    resp = client.get(
        "/users/me/bnet/start",
        headers=member() | {"x-forwarded-proto": "https"},
    )

    assert resp.status_code == 200, resp.text
    url = urlparse(resp.json()["url"])
    query = {k: v[0] for k, v in parse_qs(url.query).items()}
    assert f"{url.scheme}://{url.netloc}{url.path}" == (
        "https://oauth.battle.net/authorize"
    )
    assert query["client_id"] == "client-1"
    assert query["response_type"] == "code"
    assert query["scope"] == "openid"
    assert query["redirect_uri"] == "https://testserver/auth/battlenet/callback"
    assert "secret-1" not in resp.text
    claims = decode_token(query["state"])
    assert (claims["sub"], claims["type"]) == ("1", "bnet_state")


def test_start_answers_503_when_battle_net_is_not_configured(
    client: Client,
    seeded: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    member: Callable[..., dict[str, str]],
) -> None:
    monkeypatch.delenv("BNET_CLIENT_ID", raising=False)
    monkeypatch.delenv("BNET_CLIENT_SECRET", raising=False)

    resp = client.get("/users/me/bnet/start", headers=member())

    assert resp.status_code == 503
    assert resp.json() == {"error": "Battle.net login is not configured"}


def test_the_state_is_no_login(client: Client, seeded: dict[str, Any]) -> None:
    state = create_access_token("1", 10, "bnet_state")

    resp = client.get(
        "/users/me/bnet/start", headers={"Authorization": f"Bearer {state}"}
    )

    assert resp.status_code == 422


# GET /auth/battlenet/callback


def test_a_tag_the_member_holds_becomes_verified_and_active(
    client: Client,
    seeded: dict[str, Any],
    bnet_env: None,
    blizzard: Callable[[str, str], None],
) -> None:
    blizzard("acc-1", "p1#1111")

    assert callback(client) == LINKED
    assert rows_of(seeded["player_ids"][0]) == [("P1#1111", "link", True, "acc-1")]


def test_a_tag_new_to_the_app_is_added_verified_and_active(
    client: Client,
    seeded: dict[str, Any],
    bnet_env: None,
    blizzard: Callable[[str, str], None],
) -> None:
    blizzard("acc-1", "New#4242")

    assert callback(client) == LINKED
    assert rows_of(seeded["player_ids"][0]) == [
        ("P1#1111", "signup", False, None),
        ("New#4242", "link", True, "acc-1"),
    ]


def test_a_tag_a_person_with_no_login_holds_moves_to_the_member(
    client: Client,
    seeded: dict[str, Any],
    bnet_env: None,
    blizzard: Callable[[str, str], None],
) -> None:
    old = no_login_person()
    blizzard("acc-1", "Old#5555")

    assert callback(client) == LINKED
    assert rows_of(old) == []
    assert rows_of(seeded["player_ids"][0]) == [
        ("P1#1111", "signup", False, None),
        ("Old#5555", "link", True, "acc-1"),
    ]


def test_a_tag_another_login_holds_is_taken(
    client: Client,
    seeded: dict[str, Any],
    bnet_env: None,
    blizzard: Callable[[str, str], None],
) -> None:
    blizzard("acc-1", "P2#2222")

    assert callback(client) == error("taken")
    assert rows_of(seeded["player_ids"][1]) == [("P2#2222", "signup", True, None)]
    assert rows_of(seeded["player_ids"][0]) == [("P1#1111", "signup", True, None)]


def test_an_account_another_person_holds_is_taken(
    client: Client,
    seeded: dict[str, Any],
    bnet_env: None,
    blizzard: Callable[[str, str], None],
) -> None:
    blizzard("acc-2", "P2#2222")
    assert callback(client, "2") == LINKED

    blizzard("acc-2", "P1#1111")

    assert callback(client) == error("taken")
    assert rows_of(seeded["player_ids"][0]) == [("P1#1111", "signup", True, None)]


def test_a_renamed_account_keeps_its_old_row(
    client: Client,
    seeded: dict[str, Any],
    bnet_env: None,
    blizzard: Callable[[str, str], None],
) -> None:
    blizzard("acc-1", "P1#1111")
    assert callback(client) == LINKED

    blizzard("acc-1", "Renamed#1111")

    assert callback(client) == LINKED
    assert rows_of(seeded["player_ids"][0]) == [
        ("P1#1111", "link", False, "acc-1"),
        ("Renamed#1111", "link", True, "acc-1"),
    ]


@pytest.mark.parametrize(
    "state",
    [
        "not-a-token",
        create_access_token("1", -1, "bnet_state"),
        create_access_token("1", 10),
    ],
    ids=["garbage", "expired", "login-token"],
)
def test_a_bad_state_changes_nothing(
    client: Client,
    seeded: dict[str, Any],
    bnet_env: None,
    blizzard: Callable[[str, str], None],
    state: str,
) -> None:
    blizzard("acc-1", "P1#1111")

    resp = client.get("/auth/battlenet/callback", params={"code": "c", "state": state})

    assert resp.headers["location"] == error("state")
    assert rows_of(seeded["player_ids"][0]) == [("P1#1111", "signup", True, None)]


def test_a_member_who_cancels_on_battle_net_is_denied(
    client: Client, seeded: dict[str, Any], bnet_env: None
) -> None:
    location = callback(client, code="", error="access_denied")

    assert location == error("denied")


def test_a_refused_code_is_a_token_error(
    client: Client,
    seeded: dict[str, Any],
    bnet_env: None,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def refuse(code: str, uri: str) -> str:
        raise requests.HTTPError("400")

    monkeypatch.setattr(battlenet, "_exchange_code", refuse)

    assert callback(client) == error("token")
    assert rows_of(seeded["player_ids"][0]) == [("P1#1111", "signup", True, None)]
