"""The tag routes: a member's own tags, and an admin's move and merge.

A member adds a tag they also played as, picks the active one and removes an
unverified spare. An admin moves one tag row to another person, or merges
two people into one; the merge finds every user id column from the table
metadata and refuses when both people hold a row one unique key allows once.
"""

from collections.abc import Callable
from datetime import UTC, datetime
from typing import Any

import pytest
from httpx2 import Client
from sqlalchemy import select
from sqlmodel import col

from app.core.db import Session
from app.models.enums import Race
from app.models.ladder_sync import LadderSync
from app.models.relationships import DBUserSeasonSignup
from app.models.series import Series
from app.models.user import User
from app.models.user_battle_tag import UserBattleTag
from app.models.w3c_ladder_match import W3CLadderMatch
from app.services import merge
from app.services.users import UserService
from tests.test_battle_tag_reads import second_tag

DAY = datetime(2026, 3, 1, tzinfo=UTC)


@pytest.fixture
def on_w3c(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(UserService, "validate_battle_tag", lambda self, tag: True)


def no_login_person(tag: str = "Old#5555", name: str = "Old") -> int:
    """A person from an earlier season: one active tag, no Discord id."""
    with Session.begin() as session:
        user = User(name=name, discordId=None, race=Race.HU)
        session.add(user)
        session.flush()
        assert user.id is not None
        session.add(
            UserBattleTag(user_id=user.id, tag=tag, source="sheet", is_active=True)
        )
        return user.id


def ladder_match(user_id: int, match_id: str, tag_id: int | None = None) -> None:
    with Session.begin() as session:
        session.add(
            W3CLadderMatch(
                w3c_match_id=match_id,
                wc3_season=22,
                start_time=DAY,
                duration_s=600,
                won=True,
                user_id=user_id,
                battle_tag_id=tag_id,
            )
        )


def ledger(user_id: int, synced_at: datetime = DAY) -> None:
    with Session.begin() as session:
        session.add(LadderSync(user_id=user_id, wc3_season=22, synced_at=synced_at))


def signup(user_id: int, season_id: int) -> None:
    with Session.begin() as session:
        session.add(
            DBUserSeasonSignup(user_id=user_id, season_id=season_id, race=Race.HU)
        )


def tags_of(user_id: int) -> list[tuple[str, str, bool]]:
    with Session() as session:
        rows = session.scalars(
            select(UserBattleTag)
            .where(col(UserBattleTag.user_id) == user_id)
            .order_by(col(UserBattleTag.id))
        ).all()
        return [(row.tag, row.source, row.is_active) for row in rows]


def count(model: type, **where: int) -> int:
    with Session() as session:
        statement = select(model)
        for name, value in where.items():
            statement = statement.where(getattr(model, name) == value)
        return len(session.scalars(statement).all())


# Member: POST /users/me/tags


def test_a_tag_a_person_with_no_login_holds_joins_that_person_to_the_member(
    client: Client,
    seeded: dict[str, Any],
    on_w3c: None,
    member: Callable[..., dict[str, str]],
) -> None:
    old = no_login_person()

    resp = client.post("/users/me/tags", json={"tag": "old#5555"}, headers=member())

    assert resp.status_code == 200, resp.text
    assert resp.json()["battleTag"] == "P1#1111"
    assert {(t["tag"], t["source"], t["active"]) for t in resp.json()["tags"]} == {
        ("P1#1111", "signup", True),
        ("Old#5555", "sheet", False),
    }
    with Session() as session:
        assert session.get(User, old) is None


def test_a_tag_new_to_the_app_is_added_unverified_and_inactive(
    client: Client,
    seeded: dict[str, Any],
    on_w3c: None,
    member: Callable[..., dict[str, str]],
) -> None:
    resp = client.post("/users/me/tags", json={"tag": "Alt#7777"}, headers=member())

    assert resp.status_code == 200, resp.text
    added = [t for t in resp.json()["tags"] if t["tag"] == "Alt#7777"]
    assert [(t["source"], t["active"], t["verified"]) for t in added] == [
        ("claim", False, False)
    ]


def test_a_tag_another_login_holds_answers_409(
    client: Client,
    seeded: dict[str, Any],
    on_w3c: None,
    member: Callable[..., dict[str, str]],
) -> None:
    resp = client.post("/users/me/tags", json={"tag": "P2#2222"}, headers=member())

    assert resp.status_code == 409
    assert resp.json() == {
        "error": "P2#2222 belongs to another player. Ask an admin to move it."
    }
    assert tags_of(seeded["player_ids"][1]) == [("P2#2222", "signup", True)]


def test_a_tag_w3champions_does_not_know_answers_404(
    client: Client,
    seeded: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
    member: Callable[..., dict[str, str]],
) -> None:
    monkeypatch.setattr(UserService, "validate_battle_tag", lambda self, tag: False)

    resp = client.post("/users/me/tags", json={"tag": "Nobody#1"}, headers=member())

    assert resp.status_code == 404
    assert "Nobody#1" in resp.json()["error"]
    assert len(tags_of(seeded["player_ids"][0])) == 1


# Member: PUT /users/me/tags/{tag_id}/active


def test_a_member_makes_a_second_tag_active(
    client: Client, seeded: dict[str, Any], member: Callable[..., dict[str, str]]
) -> None:
    smurf = second_tag(seeded["player_ids"][0])

    resp = client.put(f"/users/me/tags/{smurf}/active", headers=member())

    assert resp.status_code == 200, resp.text
    assert resp.json()["battleTag"] == "Smurf#2222"
    assert {(t["tag"], t["active"]) for t in resp.json()["tags"]} == {
        ("Smurf#2222", True),
        ("P1#1111", False),
    }


def test_a_member_cannot_activate_another_players_tag(
    client: Client, seeded: dict[str, Any], member: Callable[..., dict[str, str]]
) -> None:
    theirs = second_tag(seeded["player_ids"][1])

    resp = client.put(f"/users/me/tags/{theirs}/active", headers=member())

    assert resp.status_code == 404
    assert tags_of(seeded["player_ids"][1])[1] == ("Smurf#2222", "sheet", False)


# Member: DELETE /users/me/tags/{tag_id}


def test_removing_a_tag_removes_its_matches_and_the_ledger(
    client: Client, seeded: dict[str, Any], member: Callable[..., dict[str, str]]
) -> None:
    p1 = seeded["player_ids"][0]
    smurf = second_tag(p1)
    ladder_match(p1, "m-smurf", smurf)
    ladder_match(p1, "m-main")
    ledger(p1)

    resp = client.delete(f"/users/me/tags/{smurf}", headers=member())

    assert resp.status_code == 200, resp.text
    assert [t["tag"] for t in resp.json()["tags"]] == ["P1#1111"]
    with Session() as session:
        left = session.scalars(
            select(col(W3CLadderMatch.w3c_match_id)).where(
                col(W3CLadderMatch.user_id) == p1
            )
        ).all()
    assert left == ["m-main"]
    assert count(LadderSync, user_id=p1) == 0


def test_the_active_tag_cannot_be_removed(
    client: Client, seeded: dict[str, Any], member: Callable[..., dict[str, str]]
) -> None:
    body = client.get(f"/users/{seeded['player_ids'][0]}").json()
    active = body["tags"][0]["id"]

    resp = client.delete(f"/users/me/tags/{active}", headers=member())

    assert resp.status_code == 409
    assert "error" in resp.json()


# Admin: POST /users/{id}/tags/{tag_id}/move


def test_moving_the_active_tag_activates_the_newest_left(
    client: Client, seeded: dict[str, Any], auth_headers: dict[str, str]
) -> None:
    p1, p2 = seeded["player_ids"][:2]
    smurf = second_tag(p1)
    main = client.get(f"/users/{p1}").json()["tags"][0]["id"]
    ledger(p1)
    ledger(p2)

    resp = client.post(
        f"/users/{p1}/tags/{main}/move", json={"to_user_id": p2}, headers=auth_headers
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["id"] == p2
    assert resp.json()["battleTag"] == "P2#2222"
    assert set(tags_of(p2)) == {
        ("P2#2222", "signup", True),
        ("P1#1111", "admin", False),
    }
    assert client.get(f"/users/{p1}").json()["battleTag"] == "Smurf#2222"
    assert tags_of(p1) == [("Smurf#2222", "sheet", True)]
    assert count(LadderSync) == 0
    assert smurf


def test_moving_the_only_tag_to_a_person_with_none_makes_it_theirs_and_active(
    client: Client, seeded: dict[str, Any], auth_headers: dict[str, str]
) -> None:
    old = no_login_person()
    with Session.begin() as session:
        user = session.get(User, old)
        assert user is not None
        empty = User(name="Empty", discordId="77", race=Race.HU)
        session.add(empty)
        session.flush()
        empty_id = empty.id
    tag_id = client.get(f"/users/{old}").json()["tags"][0]["id"]

    resp = client.post(
        f"/users/{old}/tags/{tag_id}/move",
        json={"to_user_id": empty_id},
        headers=auth_headers,
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["battleTag"] == "Old#5555"
    assert client.get(f"/users/{old}").json()["battleTag"] is None


# Admin: POST /users/{id}/merge


def test_the_merge_finds_every_user_column_from_the_metadata() -> None:
    columns = merge.user_columns()

    for table, column in [
        ("user_season_signup", "user_id"),
        ("user_team_season", "user_id"),
        ("round_availability", "set_by_user_id"),
        ("series", "player2_id"),
        ("series", "host_player_id"),
        ("series_side", "user_id"),
        ("draft_series", "created_by_user_id"),
        ("fantasy_bets", "winner_id"),
        ("w3c_ladder_matches", "user_id"),
        ("user_battle_tag", "user_id"),
    ]:
        assert column in columns[table], (table, column)


def test_the_known_unique_keys_stop_a_merge() -> None:
    keys = merge.unique_keys()

    assert ("user_id", "season_id") in keys["user_season_signup"]
    assert ("user_id", "team_id", "season_id") in keys["user_team_season"]
    assert ("user_id", "season_id", "playday") in keys["round_availability"]
    assert ("series_id", "user_id") in keys["fantasy_bets"]
    assert ("series_id", "user_id") in keys["series_side"]
    assert ("event_id", "user_id", "race") in keys["event_entrant"]
    assert ("season_id", "captain_id") in keys["fantasy_teams"]


def both_signed_up_with_one_ladder_game(seeded: dict[str, Any]) -> tuple[int, int]:
    old, p3 = no_login_person(), seeded["player_ids"][2]
    signup(old, seeded["season_id"])
    signup(p3, seeded["season_id"])
    ladder_match(old, "same-game")
    ladder_match(p3, "same-game")
    return old, p3


def test_a_dry_run_lists_a_stop_and_a_removal(
    client: Client, seeded: dict[str, Any], auth_headers: dict[str, str]
) -> None:
    old, p3 = both_signed_up_with_one_ladder_game(seeded)

    resp = client.post(
        f"/users/{old}/merge",
        json={"into_user_id": p3, "dry_run": True},
        headers=auth_headers,
    )

    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert len(body["stops"]) == 1
    assert "signup" in body["stops"][0]
    assert body["removes"] == ["1 duplicate ladder match"]
    assert "1 battle tag" in body["moves"]
    assert count(User, id=old) == 1


def test_a_real_run_with_a_stop_answers_409_and_changes_nothing(
    client: Client, seeded: dict[str, Any], auth_headers: dict[str, str]
) -> None:
    old, p3 = both_signed_up_with_one_ladder_game(seeded)

    resp = client.post(
        f"/users/{old}/merge",
        json={"into_user_id": p3, "dry_run": False},
        headers=auth_headers,
    )

    assert resp.status_code == 409
    body = resp.json()
    assert body["error"]
    assert len(body["stops"]) == 1
    assert body["removes"] == ["1 duplicate ladder match"]
    assert count(User, id=old) == 1
    assert count(W3CLadderMatch, user_id=old) == 1


def test_a_real_run_repoints_every_row_and_removes_the_person(
    client: Client, seeded: dict[str, Any], auth_headers: dict[str, str]
) -> None:
    old, p3 = no_login_person(), seeded["player_ids"][2]
    signup(old, seeded["season_id"])
    ladder_match(old, "same-game")
    ladder_match(p3, "same-game")
    ladder_match(old, "only-old")
    ledger(old, datetime(2026, 1, 1, tzinfo=UTC))
    ledger(p3, datetime(2026, 2, 1, tzinfo=UTC))
    with Session.begin() as session:
        series = session.get(Series, seeded["series_open_id"])
        assert series is not None
        series.player2_id = old
        series.host_player_id = old

    resp = client.post(
        f"/users/{old}/merge", json={"into_user_id": p3}, headers=auth_headers
    )

    assert resp.status_code == 200, resp.text
    assert resp.json()["id"] == p3
    assert resp.json()["battleTag"] == "P3#3333"
    assert count(User, id=old) == 0
    assert tags_of(p3) == [("P3#3333", "signup", True), ("Old#5555", "sheet", False)]
    assert count(DBUserSeasonSignup, user_id=p3) == 1
    assert count(W3CLadderMatch, user_id=p3) == 2
    with Session() as session:
        series = session.get(Series, seeded["series_open_id"])
        assert series is not None
        assert (series.player2_id, series.host_player_id) == (p3, p3)
        synced = session.scalars(select(LadderSync)).all()
    assert [(row.user_id, row.synced_at.month) for row in synced] == [(p3, 2)]


# GET /users filters


def test_the_users_list_filters_people_with_no_login(
    client: Client, seeded: dict[str, Any]
) -> None:
    old = no_login_person()
    no_login_person("Older#6666", "Older")

    resp = client.get("/users", params={"no_discord": True, "limit": 1})

    assert resp.status_code == 200, resp.text
    assert [row["id"] for row in resp.json()] == [old]
    assert resp.headers["X-Total-Count"] == "2"


def test_the_users_list_filters_people_by_tag_source(
    client: Client,
    seeded: dict[str, Any],
    on_w3c: None,
    member: Callable[..., dict[str, str]],
) -> None:
    client.post("/users/me/tags", json={"tag": "Alt#7777"}, headers=member())

    resp = client.get("/users", params={"tag_source": "claim", "offset": 0})

    assert [row["id"] for row in resp.json()] == [seeded["player_ids"][0]]
    assert resp.headers["X-Total-Count"] == "1"
