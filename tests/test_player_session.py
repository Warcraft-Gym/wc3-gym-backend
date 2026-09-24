"""The player routes identify the member by their Clerk session.

The session names the Discord account; the profile form and the dashboard
never carry the identity themselves.
"""

from typing import Any

import pytest
from fastapi import FastAPI
from httpx2 import Client, Response

from tests.test_discord_auth import SESSION, stub_clerk


@pytest.fixture
def w3c_free(monkeypatch: pytest.MonkeyPatch, app: FastAPI) -> None:
    """Signup calls W3Champions twice. Answer both without the network."""
    from app.services.users import UserService

    monkeypatch.setattr(UserService, "validate_battle_tag", lambda self, tag: True)
    monkeypatch.setattr(
        UserService, "update_w3c_stats_by_id", lambda self, user_id: None
    )


SIGNUP_BODY = {"name": "P9", "battleTag": "P9#1234", "race": "HU", "country": "DE"}


def member_session(
    monkeypatch: pytest.MonkeyPatch,
    discord_id: str = "1",
    name: str = "p1",
    a_member: bool = True,
) -> dict[str, str]:
    """Stand Clerk and Discord in for one account, and answer the headers it sends."""
    stub_clerk(
        monkeypatch,
        a_member=a_member,
        account={"id": discord_id, "username": name, "avatar": None},
    )
    return SESSION


@pytest.fixture
def member_headers(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    return member_session(monkeypatch)


def test_signup_takes_the_discord_fields_from_the_session(
    client: Client, w3c_free: None, member_headers: dict[str, str]
) -> None:
    """The session wins over the body."""
    resp = client.post(
        "/signup", json=SIGNUP_BODY | {"discordId": "999"}, headers=member_headers
    )

    assert resp.status_code == 201, resp.text
    assert resp.json()["discordId"] == "1"
    assert resp.json()["discordTag"] == "p1"


def test_a_re_signup_keeps_the_fields_the_form_leaves_out(
    client: Client,
    seeded: dict[str, Any],
    w3c_free: None,
    member_headers: dict[str, str],
) -> None:
    """The join card posts no mmr, so a re-save must not clear the stored one."""
    assert client.get("/users/1").json()["mmr"] == 1500

    resp = client.post(
        "/signup",
        json=SIGNUP_BODY | {"name": "P1", "battleTag": "P1#1111", "country": "SE"},
        headers=member_headers,
    )

    assert resp.status_code == 201, resp.text
    assert resp.json()["mmr"] == 1500
    assert resp.json()["country"] == "SE"


def test_player_series_on_a_session_reads_the_current_season(
    client: Client, seeded: dict[str, Any], member_headers: dict[str, str]
) -> None:
    """A signed-in player has no token to carry the season, so the pinned one is used.

    A newer season is stored and the setting names the older one. Without it the
    fallback to the highest season id would answer the newer season, which
    carries no rounds.
    """
    from app.core.db import Session
    from app.models.season import Season
    from app.models.settings import Settings

    with Session() as session:
        session.add(Season(name="Later Season", series_per_round=2))
        session.add(Settings(key="current_gnl_season", value=str(seeded["season_id"])))
        session.commit()

    body = client.get("/player-series", headers=member_headers).json()

    assert body["season_id"] == seeded["season_id"]
    assert body["round_count"] == 4
    assert body["availability"] == []


def test_player_series_answers_404_for_a_member_without_a_row(
    client: Client, seeded: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    headers = member_session(monkeypatch, "no-such-id")

    resp = client.get("/player-series", headers=headers)

    assert resp.status_code == 404, resp.text
    assert resp.json() == {"error": "player_not_found"}


def test_an_admin_token_carries_no_discord_id(
    client: Client, seeded: dict[str, Any], auth_headers: dict[str, str]
) -> None:
    """The bot's admin token logs in as no player, so a player route turns it away."""
    resp = client.get("/player-series", headers=auth_headers)

    assert resp.status_code == 401, resp.text
    assert resp.json() == {"error": "not_a_discord_member"}


def test_a_guest_reads_no_player_route(
    client: Client, seeded: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """An account outside the guild logs in, and the player routes turn it away."""
    headers = member_session(monkeypatch, a_member=False)

    resp = client.get("/player-series", headers=headers)

    assert resp.status_code == 403, resp.text
    assert resp.json() == {"error": "No valid WC3 Gym server membership found for user"}


def test_signup_stores_the_time_zone(
    client: Client, w3c_free: None, member_headers: dict[str, str]
) -> None:
    """The profile form sends the browser's IANA name."""
    resp = client.post(
        "/signup",
        json=SIGNUP_BODY | {"timezone": "America/New_York"},
        headers=member_headers,
    )

    assert resp.status_code == 201, resp.text
    assert resp.json()["timezone"] == "America/New_York"


def test_signup_refuses_an_unknown_time_zone(
    client: Client, w3c_free: None, member_headers: dict[str, str]
) -> None:
    resp = client.post(
        "/signup",
        json=SIGNUP_BODY | {"timezone": "Mars/Olympus"},
        headers=member_headers,
    )

    assert resp.status_code == 422, resp.text
    assert "Mars/Olympus" in resp.json()["error"]
    assert client.get("/users").json() == []


# Which player row a member signup writes. The login's own row first. A tag no
# login holds is claimed by the login that types it exactly; a tag another
# login holds is refused. A row that holds only the login's Discord name is a
# guess an admin confirms, so it is refused.


def _player(name: str, tag: str, discord_id: str = "", discord_tag: str = "") -> int:
    from app.core.db import Session
    from app.models.enums import Race
    from app.models.user import User

    with Session() as session:
        user = User(
            name=name,
            battleTag=tag,
            discordTag=discord_tag,
            discordId=discord_id,
            race=Race.HU,
        )
        session.add(user)
        session.commit()
        assert user.id is not None
        return user.id


def _row(user_id: int) -> dict[str, Any]:
    from app.core.db import Session
    from app.models.user import User

    with Session() as session:
        user = session.get(User, user_id)
        assert user is not None
        return {
            "discordId": user.discordId,
            "discordTag": user.discordTag,
            "battleTag": user.battleTag,
        }


def _signup(
    client: Client,
    monkeypatch: pytest.MonkeyPatch,
    tag: str,
    discord_id: str = "1",
    name: str = "p1",
) -> Response:
    headers = member_session(monkeypatch, discord_id=discord_id, name=name)
    return client.post(
        "/signup", json=SIGNUP_BODY | {"battleTag": tag}, headers=headers
    )


def test_a_tag_no_login_holds_is_claimed(
    app: FastAPI, client: Client, w3c_free: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A KOTH entrant signs up for the league with the same tag: one player."""
    koth = _player("X", "X#1234")

    resp = _signup(client, monkeypatch, "x#1234")

    assert resp.status_code == 201, resp.text
    assert resp.json()["id"] == koth
    assert _row(koth)["discordId"] == "1"


def test_a_history_stand_in_counts_as_no_login(
    app: FastAPI, client: Client, w3c_free: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """A player from an earlier season carries a gnl- stand-in, not a login."""
    earlier = _player(
        "BELIT", "BeLit#11855", discord_id="gnl-s12-17", discord_tag="fattsrussell#6428"
    )

    resp = _signup(client, monkeypatch, "BeLit#11855")

    assert resp.status_code == 201, resp.text
    assert resp.json()["id"] == earlier
    assert _row(earlier)["discordId"] == "1"


def test_a_tag_another_login_holds_is_refused(
    app: FastAPI, client: Client, w3c_free: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    held = _player("Owner", "X#1234", discord_id="777", discord_tag="owner")

    resp = _signup(client, monkeypatch, "X#1234")

    assert resp.status_code == 409, resp.text
    assert "X#1234" in resp.json()["error"]
    assert _row(held)["discordId"] == "777"


def test_a_second_login_typing_a_claimed_tag_is_refused(
    app: FastAPI, client: Client, w3c_free: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    earlier = _player("X", "X#1234")
    assert _signup(client, monkeypatch, "X#1234").status_code == 201

    resp = _signup(client, monkeypatch, "X#1234", discord_id="2", name="p2")

    assert resp.status_code == 409, resp.text
    assert _row(earlier)["discordId"] == "1"


def test_a_row_holding_only_the_discord_name_needs_an_admin(
    app: FastAPI, client: Client, w3c_free: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The name alone is a guess: nothing is written, and the answer carries
    what an admin needs to link the row."""
    earlier = _player("Old", "Old#1111", discord_tag="p1")

    resp = _signup(client, monkeypatch, "New#2222")

    assert resp.status_code == 409, resp.text
    assert resp.json()["link"] == {
        "player": "Old",
        "discord_id": "1",
        "battle_tag": "New#2222",
    }
    assert _row(earlier) == {
        "discordId": "",
        "discordTag": "p1",
        "battleTag": "Old#1111",
    }


def test_a_namesake_with_a_login_is_left_alone(
    app: FastAPI, client: Client, w3c_free: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Discord names repeat. Another login's row is never rewritten, and the new
    row leaves the repeated name out rather than break its unique index."""
    namesake = _player("Other", "Other#3333", discord_id="888", discord_tag="p1")

    resp = _signup(client, monkeypatch, "Mine#4444")

    assert resp.status_code == 201, resp.text
    assert resp.json()["id"] != namesake
    assert resp.json()["discordTag"] == ""
    assert _row(namesake)["discordId"] == "888"


def test_an_own_row_typing_an_earlier_players_tag_needs_an_admin(
    app: FastAPI, client: Client, w3c_free: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Two rows would become one person: that is a merge, never a signup."""
    _player("Me", "Me#5555", discord_id="1", discord_tag="p1")
    earlier = _player("Old me", "OldMe#6666")

    resp = _signup(client, monkeypatch, "OldMe#6666")

    assert resp.status_code == 409, resp.text
    assert "OldMe#6666" in resp.json()["error"]
    assert _row(earlier)["discordId"] == ""


def test_nothing_matching_makes_a_new_player(
    app: FastAPI, client: Client, w3c_free: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    resp = _signup(client, monkeypatch, "Fresh#7777")

    assert resp.status_code == 201, resp.text
    assert resp.json()["discordId"] == "1"
    assert resp.json()["discordTag"] == "p1"


def test_a_discord_name_matches_without_case(
    app: FastAPI, client: Client, w3c_free: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    """The unique index folds case, so the lookup folds it too."""
    _player("Old", "Old#1111", discord_tag="P1")

    resp = _signup(client, monkeypatch, "Fresh#7777")

    assert resp.status_code == 409, resp.text
    assert resp.json()["link"]["player"] == "Old"


def test_a_namesake_differing_only_in_case_is_left_alone(
    app: FastAPI, client: Client, w3c_free: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    namesake = _player("Other", "Other#3333", discord_id="888", discord_tag="P1")

    resp = _signup(client, monkeypatch, "Mine#4444")

    assert resp.status_code == 201, resp.text
    assert resp.json()["discordTag"] == ""
    assert _row(namesake)["discordId"] == "888"
