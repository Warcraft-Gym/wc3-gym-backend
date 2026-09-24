"""Suggestions of an earlier player, and the notice of a tag taken by a verify.

Only a tag Battle.net verified joins an earlier player to a login unasked. A
login holding the sheet's tag unverified, a name-search guess, or the sheet's
Discord name gets a suggestion it answers once; a player two logins could be
is suggested to neither. An admin moving a tag never makes it verified.
"""

import io
from collections.abc import Callable
from typing import Any

from httpx2 import Client
from sqlalchemy import select
from sqlmodel import col

from app.core.db import Session
from app.models.enums import Race
from app.models.link_prompt import LinkPrompt
from app.models.relationships import DBUserSeasonSignup
from app.models.user import User
from app.models.user_battle_tag import UserBattleTag
from app.services.link_prompts import suggest
from tests.conftest import write_workbook
from tests.test_battlenet_link import finish
from tests.test_season_import import SHEETS, _post
from tests.test_tag_routes import no_login_person


def _suggest(
    person_id: int, reason: str, tag: str | None = None, user_id: int | None = None
) -> None:
    with Session.begin() as session:
        person = session.get(User, person_id)
        assert person is not None
        suggest(session, person, reason, tag=tag, user_id=user_id)


def _prompts(client: Client, headers: dict[str, str]) -> list[dict[str, Any]]:
    resp = client.get("/users/me/prompts", headers=headers)
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_the_login_holding_the_tag_sees_the_suggestion_and_accepting_joins(
    client: Client, seeded: dict[str, Any], member: Callable[..., dict[str, str]]
) -> None:
    old = no_login_person("Older#1234", "Old")
    _suggest(old, "sheet", tag="p1#1111")

    [prompt] = _prompts(client, member())
    assert (prompt["kind"], prompt["name"], prompt["tag"]) == (
        "suggest",
        "Old",
        "p1#1111",
    )
    assert _prompts(client, member("2")) == []

    resp = client.post(
        f"/users/me/prompts/{prompt['id']}", json={"accept": True}, headers=member()
    )

    assert resp.status_code == 200, resp.text
    assert {(t["tag"], t["verified"]) for t in resp.json()["tags"]} == {
        ("P1#1111", False),
        ("Older#1234", False),
    }
    with Session() as session:
        assert session.get(User, old) is None
    assert _prompts(client, member()) == []


def test_a_dismissed_suggestion_never_comes_back(
    client: Client, seeded: dict[str, Any], member: Callable[..., dict[str, str]]
) -> None:
    old = no_login_person()
    _suggest(old, "sheet", tag="P1#1111")
    [prompt] = _prompts(client, member())

    resp = client.post(
        f"/users/me/prompts/{prompt['id']}", json={"accept": False}, headers=member()
    )

    assert resp.status_code == 200, resp.text
    assert _prompts(client, member()) == []
    with Session() as session:
        assert session.get(User, old) is not None


def test_one_dismiss_closes_every_suggestion_of_the_player_to_the_login(
    client: Client, seeded: dict[str, Any], member: Callable[..., dict[str, str]]
) -> None:
    old = no_login_person()
    _suggest(old, "sheet", tag="P1#1111")
    _suggest(old, "discord", user_id=seeded["player_ids"][0])
    [prompt] = _prompts(client, member())

    resp = client.post(
        f"/users/me/prompts/{prompt['id']}", json={"accept": False}, headers=member()
    )

    assert resp.status_code == 200, resp.text
    assert _prompts(client, member()) == []


def test_a_player_two_logins_could_be_is_suggested_to_neither(
    client: Client, seeded: dict[str, Any], member: Callable[..., dict[str, str]]
) -> None:
    old = no_login_person()
    _suggest(old, "sheet", tag="P1#1111")
    _suggest(old, "discord", user_id=seeded["player_ids"][1])

    assert _prompts(client, member()) == []
    assert _prompts(client, member("2")) == []


def test_another_logins_prompt_cannot_be_answered(
    client: Client, seeded: dict[str, Any], member: Callable[..., dict[str, str]]
) -> None:
    old = no_login_person()
    _suggest(old, "sheet", tag="P1#1111")
    [prompt] = _prompts(client, member())

    resp = client.post(
        f"/users/me/prompts/{prompt['id']}", json={"accept": True}, headers=member("2")
    )

    assert resp.status_code == 404
    with Session() as session:
        assert session.get(User, old) is not None


def test_an_admin_move_leaves_the_tag_unverified(
    client: Client,
    seeded: dict[str, Any],
    member: Callable[..., dict[str, str]],
    auth_headers: dict[str, str],
) -> None:
    p1, p2 = seeded["player_ids"][:2]
    with Session.begin() as session:
        row = session.scalars(
            select(UserBattleTag).where(col(UserBattleTag.user_id) == p1)
        ).one()
        row.bnet_account_id = "acc-1"
        tag_id = row.id

    resp = client.post(
        f"/users/{p1}/tags/{tag_id}/move", json={"to_user_id": p2}, headers=auth_headers
    )

    assert resp.status_code == 200, resp.text
    assert {(t["tag"], t["verified"]) for t in resp.json()["tags"]} >= {
        ("P1#1111", False)
    }


def _login(discord_id: str, tag: str, account: str | None = None) -> int:
    with Session.begin() as session:
        user = User(name=f"login{discord_id}", discordId=discord_id, race=Race.HU)
        session.add(user)
        session.flush()
        assert user.id is not None
        session.add(
            UserBattleTag(
                user_id=user.id,
                tag=tag,
                source="signup",
                is_active=True,
                bnet_account_id=account,
            )
        )
        return user.id


def _history_book(**suggested: str) -> io.BytesIO:
    """The default workbook with P1 as an earlier player (no Discord), and a
    Suggested Tag column."""
    columns, rows = SHEETS["Players"]
    # a history workbook writes stand-ins where the sheet has no Discord account
    rows = [
        [*r[:3], "P1#GNL01", "gnl-p1", *r[5:]] if r[1] == "P1" else list(r)
        for r in rows
    ]
    sheets = dict(SHEETS)
    sheets["Players"] = (
        [*columns, "Suggested Tag"],
        [[*r, suggested.get(r[1])] for r in rows],
    )
    return write_workbook(sheets)


def _signed_up(user_id: int) -> bool:
    with Session() as session:
        return (
            session.scalars(
                select(DBUserSeasonSignup).where(
                    col(DBUserSeasonSignup.user_id) == user_id
                )
            ).first()
            is not None
        )


def test_an_import_suggests_a_player_whose_tag_a_login_holds_unverified(
    client: Client, auth_headers: dict[str, str], member: Callable[..., dict[str, str]]
) -> None:
    login = _login("900", "P1#1111")

    assert _post(client, _history_book(), auth_headers).status_code == 200

    assert not _signed_up(login)
    [prompt] = _prompts(client, member("900"))
    assert (prompt["name"], prompt["seasons"]) == ("P1", ["Season 9"])
    with Session() as session:
        person = session.get(User, prompt["person_id"])
        assert person is not None and person.battleTag is None


def test_an_import_joins_a_login_that_verified_the_tag(
    client: Client, auth_headers: dict[str, str], member: Callable[..., dict[str, str]]
) -> None:
    login = _login("900", "P1#1111", account="acc-1")

    assert _post(client, _history_book(), auth_headers).status_code == 200

    assert _signed_up(login)
    assert _prompts(client, member("900")) == []


def test_a_suggested_tag_is_a_suggestion_and_no_tag_row(
    client: Client, auth_headers: dict[str, str], member: Callable[..., dict[str, str]]
) -> None:
    _login("901", "Guess#4242")

    assert (
        _post(client, _history_book(P1="Guess#4242"), auth_headers).status_code == 200
    )

    [prompt] = _prompts(client, member("901"))
    assert (prompt["name"], prompt["tag"]) == ("P1", "Guess#4242")
    with Session() as session:
        reasons = session.scalars(select(col(LinkPrompt.reason))).all()
    assert reasons == ["probable"]


def test_verifying_the_tag_joins_the_player_a_sheet_suggestion_names(
    client: Client, seeded: dict[str, Any], member: Callable[..., dict[str, str]]
) -> None:
    old = no_login_person("Older#1234", "Old")
    _suggest(old, "sheet", tag="P1#1111")
    guess = no_login_person("Guess#2222", "Guess")
    _suggest(guess, "probable", tag="P1#1111")

    status, body = finish(client, member(), "acc-1", "P1#1111")

    assert status == 200, body
    with Session() as session:
        assert session.get(User, old) is None
        assert session.get(User, guess) is not None


def test_reading_the_prompts_closes_nothing(
    client: Client, seeded: dict[str, Any], member: Callable[..., dict[str, str]]
) -> None:
    _suggest(no_login_person(), "sheet", tag="P1#1111")

    first = _prompts(client, member())

    assert _prompts(client, member()) == first
    assert len(first) == 1


def _people_named(name: str) -> int:
    with Session() as session:
        return len(session.scalars(select(User).where(col(User.name) == name)).all())


def test_a_reimport_after_accept_joins_the_login_and_writes_no_second_player(
    client: Client, auth_headers: dict[str, str], member: Callable[..., dict[str, str]]
) -> None:
    login = _login("900", "P1#1111")
    assert _post(client, _history_book(), auth_headers).status_code == 200
    [prompt] = _prompts(client, member("900"))
    accepted = client.post(
        f"/users/me/prompts/{prompt['id']}",
        json={"accept": True},
        headers=member("900"),
    )
    assert accepted.status_code == 200, accepted.text

    assert _post(client, _history_book(), auth_headers).status_code == 200

    assert _signed_up(login)
    assert _people_named("P1") == 0
    assert _prompts(client, member("900")) == []


def test_a_reimport_after_dismiss_reuses_the_earlier_player(
    client: Client, auth_headers: dict[str, str], member: Callable[..., dict[str, str]]
) -> None:
    _login("900", "P1#1111")
    assert _post(client, _history_book(), auth_headers).status_code == 200
    [prompt] = _prompts(client, member("900"))
    client.post(
        f"/users/me/prompts/{prompt['id']}",
        json={"accept": False},
        headers=member("900"),
    )

    assert _post(client, _history_book(), auth_headers).status_code == 200

    assert _people_named("P1") == 1
    assert _prompts(client, member("900")) == []
