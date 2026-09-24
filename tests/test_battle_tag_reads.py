"""Every way in and every read finds a person through user_battle_tag.

A person holds many tags. Any of them finds the person; the active one is
what User.battleTag reads, and the one the MMR and the stats come from. The
ladder sync reads every tag and stamps each game with the tag it came under.
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
from app.models.relationships import DBTeamSeasonCaptain, DBUserSeasonSignup
from app.models.user import User, UserReduced
from app.models.user_battle_tag import UserBattleTag
from app.models.w3c_ladder_match import W3CLadderMatch, W3CLadderMatchCreate
from app.services.ladder import LadderService
from app.services.users import UserService
from app.services.w3c import W3CService
from tests.test_fantasy_locks import schedule, score
from tests.test_player_session import SIGNUP_BODY
from tests.test_season_import import _post, _workbook


def second_tag(user_id: int, tag: str = "Smurf#2222", source: str = "sheet") -> int:
    """Give a person a second, inactive tag."""
    with Session.begin() as session:
        row = UserBattleTag(user_id=user_id, tag=tag, source=source)
        session.add(row)
        session.flush()
        assert row.id is not None
        return row.id


@pytest.fixture
def signup_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(UserService, "validate_battle_tag", lambda self, tag: True)
    monkeypatch.setattr(UserService, "update_w3c_stats_by_id", lambda self, uid: None)


def test_an_open_signup_by_a_second_tag_finds_the_person(
    seeded: dict[str, Any],
) -> None:
    """KOTH chat, the web form and an anyone event share this lookup."""
    from app.services.events import _by_battle_tag

    p1 = seeded["player_ids"][0]
    second_tag(p1)

    with Session.begin() as session:
        user = _by_battle_tag(session, "smurf#2222", Race.HU)
        found, people = user.id, len(session.scalars(select(User)).all())

    assert found == p1
    assert people == 4


def test_a_new_tag_on_the_open_way_writes_a_person_and_a_tag_row(
    seeded: dict[str, Any],
) -> None:
    from app.services.events import _by_battle_tag

    with Session.begin() as session:
        user = _by_battle_tag(session, "Fresh#5555", Race.HU)
        user_id = user.id

    with Session() as session:
        rows = session.scalars(
            select(UserBattleTag).where(col(UserBattleTag.user_id) == user_id)
        ).all()
    assert [(row.tag, row.is_active) for row in rows] == [("Fresh#5555", True)]


def test_a_new_member_signup_writes_a_tag_row_and_played_as(
    client: Client,
    seeded: dict[str, Any],
    signup_ready: None,
    member: Callable[..., dict[str, str]],
) -> None:
    # The seeded season is open once its one played series is undone
    score(seeded["series_played_id"], None, None)
    schedule(seeded["series_played_id"], None)

    resp = client.post("/signup", json=SIGNUP_BODY, headers=member("99"))

    assert resp.status_code == 201, resp.text
    user_id = resp.json()["id"]
    with Session() as session:
        tags = session.scalars(
            select(UserBattleTag).where(col(UserBattleTag.user_id) == user_id)
        ).all()
        signup = session.get(
            DBUserSeasonSignup, {"user_id": user_id, "season_id": seeded["season_id"]}
        )
    assert [(t.tag, t.source, t.is_active) for t in tags] == [
        ("P9#1234", "signup", True)
    ]
    assert signup is not None
    assert signup.played_as == "P9#1234"


def test_a_member_signing_up_with_a_new_tag_keeps_the_old_one(
    client: Client,
    seeded: dict[str, Any],
    signup_ready: None,
    member: Callable[..., dict[str, str]],
) -> None:
    """P1 signs up as a new account: it becomes active and P1#1111 stays his."""
    resp = client.post(
        "/signup",
        json=SIGNUP_BODY | {"name": "P1", "battleTag": "New#7777"},
        headers=member("1"),
    )

    assert resp.status_code == 201, resp.text
    body = client.get(f"/users/{seeded['player_ids'][0]}").json()
    assert body["battleTag"] == "New#7777"
    assert {(t["tag"], t["active"]) for t in body["tags"]} == {
        ("New#7777", True),
        ("P1#1111", False),
    }


def test_the_import_writes_no_gnl_stand_in_discord_id(
    client: Client, auth_headers: dict[str, str]
) -> None:
    """A history player has no login: null, not the sheet's gnl- stand-in."""
    from tests.test_season_import import SHEETS

    columns, rows = SHEETS["Players"]
    at = {name: index for index, name in enumerate(columns)}
    stand_in = list(rows[0])
    stand_in[at["Discord ID"]] = "gnl-s12-17"
    stand_in[at["Discord Tag"]] = "P1#GNL01"
    book = _workbook(extra={"Players": (columns, [stand_in, *rows[1:]])})

    resp = _post(client, book, auth_headers)

    assert resp.status_code == 200, resp.text
    with Session() as session:
        user = session.scalars(
            select(User).where(col(User.battleTag) == stand_in[at["Battle Tag"]])
        ).one()
        tags = session.scalars(
            select(UserBattleTag).where(col(UserBattleTag.user_id) == user.id)
        ).all()
        signup = session.scalars(
            select(DBUserSeasonSignup).where(col(DBUserSeasonSignup.user_id) == user.id)
        ).one()
    assert (user.discordId, user.discordTag) == (None, None)
    assert [(t.tag, t.source, t.is_active) for t in tags] == [
        (stand_in[at["Battle Tag"]], "sheet", True)
    ]
    assert signup.played_as == stand_in[at["Battle Tag"]]


def test_the_import_finds_a_person_by_a_second_tag(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    from tests.test_season_import import SHEETS

    p1 = seeded["player_ids"][0]
    second_tag(p1, "Import#3333")
    columns, rows = SHEETS["Players"]
    at = {name: index for index, name in enumerate(columns)}
    renamed = list(rows[0])
    renamed[at["Battle Tag"]] = "Import#3333"

    resp = _post(
        client,
        _workbook(extra={"Players": (columns, [renamed, *rows[1:]])}),
        auth_headers,
    )

    assert resp.status_code == 200, resp.text
    with Session() as session:
        signup = session.get(
            DBUserSeasonSignup,
            {"user_id": p1, "season_id": resp.json()["season_id"]},
        )
    assert signup is not None
    assert signup.played_as == "Import#3333"


def test_a_re_import_finds_a_name_only_person_by_name(
    client: Client, auth_headers: dict[str, str]
) -> None:
    """A stand-in tag writes no tag row. The next import finds the person by
    name, whether the cell holds the stand-in or is blank, as an export writes it."""
    from tests.test_season_import import SHEETS

    columns, rows = SHEETS["Players"]
    at = {name: index for index, name in enumerate(columns)}
    nobody = [None] * len(columns)
    nobody[at["ID"]], nobody[at["Name"]], nobody[at["Race"]] = 3, "Nobody", "HU"
    nobody[at["Team ID"]] = 1
    # The history workbook's stand-in Discord pair, which the import writes null
    nobody[at["Discord Tag"]], nobody[at["Discord ID"]] = "Nobody", "gnl-nobody-gnl05"

    def ids(tag: str | None) -> list[int | None]:
        nobody[at["Battle Tag"]] = tag
        book = _workbook(extra={"Players": (columns, [*rows, nobody])})
        resp = _post(client, book, auth_headers)
        assert resp.status_code == 200, resp.text
        with Session() as session:
            return list(
                session.scalars(select(col(User.id)).where(col(User.name) == "Nobody"))
            )

    first = ids("Nobody#GNL05")

    assert ids(None) == ids("Nobody#GNL05") == first
    assert len(first) == 1
    body = client.get(f"/users/{first[0]}").json()
    assert (body["battleTag"], body["tags"]) == (None, [])


def test_the_user_battle_tag_reads_the_active_row(
    client: Client, seeded: dict[str, Any]
) -> None:
    """Null with no tag; the active row's text once one is active."""
    from app.services.battle_tags import set_active_tag

    p1 = seeded["player_ids"][0]
    smurf = second_tag(p1)
    with Session.begin() as session:
        set_active_tag(
            session, session.get_one(User, p1), session.get_one(UserBattleTag, smurf)
        )
        empty = User(name="Empty", discordId="77", race=Race.HU)
        session.add(empty)
        session.flush()
        empty_id = empty.id

    assert client.get(f"/users/{p1}").json()["battleTag"] == "Smurf#2222"
    assert client.get(f"/users/{empty_id}").json()["battleTag"] is None
    listed = client.get("/users").json()
    assert {row["id"]: row["battleTag"] for row in listed}[p1] == "Smurf#2222"


def test_an_admin_created_user_holds_the_tag_as_a_row(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    body = {
        "name": "New",
        "battleTag": "New#4444",
        "discordTag": "new",
        "discordId": "44",
        "race": "HU",
    }

    resp = client.post("/users", json=body, headers=auth_headers)

    assert resp.status_code == 201, resp.text
    assert resp.json()["battleTag"] == "New#4444"
    with Session() as session:
        row = session.scalars(
            select(UserBattleTag).where(col(UserBattleTag.user_id) == resp.json()["id"])
        ).one()
    assert (row.tag, row.source, row.is_active) == ("New#4444", "admin", True)


def test_a_user_reads_by_any_tag_they_hold(
    client: Client, seeded: dict[str, Any]
) -> None:
    p1 = seeded["player_ids"][0]
    tag_id = second_tag(p1)

    by_second = client.get("/users/SMURF%232222")

    assert by_second.status_code == 200, by_second.text
    body = by_second.json()
    assert body["id"] == p1
    assert body["battleTag"] == "P1#1111"
    smurf = next(tag for tag in body["tags"] if tag["tag"] == "Smurf#2222")
    assert set(smurf) == {
        "id",
        "tag",
        "verified",
        "active",
        "source",
        "first_seen",
        "last_seen",
    }
    assert (smurf["id"], smurf["verified"], smurf["active"], smurf["source"]) == (
        tag_id,
        False,
        False,
        "sheet",
    )
    assert body["tags"][0]["tag"] == "P1#1111"
    assert body["tags"][0]["active"] is True


def test_the_users_list_carries_the_tags_in_a_fixed_number_of_statements(
    client: Client, seeded: dict[str, Any]
) -> None:
    from tests.test_query_budget import count_statements

    with count_statements() as before:
        client.get("/users")
    for user_id in seeded["player_ids"]:
        second_tag(user_id, f"Extra{user_id}#1")
    with count_statements() as after:
        listed = client.get("/users").json()

    assert before[0] == after[0]
    assert all(len(user["tags"]) == 2 for user in listed)


def test_roster_and_signup_rows_carry_played_as(
    client: Client, seeded: dict[str, Any]
) -> None:
    p1, season_id = seeded["player_ids"][0], seeded["season_id"]
    with Session.begin() as session:
        session.add(
            DBUserSeasonSignup(
                user_id=p1, season_id=season_id, race=Race.HU, played_as="Old#1111"
            )
        )

    team = client.get(f"/events/{season_id}/teams/{seeded['team_a_id']}").json()
    user = client.get(f"/users/{p1}").json()
    signups = client.get(f"/events/{season_id}/signups").json()

    roster = {p["id"]: p["played_as"] for p in team["player_by_season"][str(season_id)]}
    assert roster[p1] == "Old#1111"
    assert [s["played_as"] for s in user["signup_seasons"]] == ["Old#1111"]
    assert next(s for s in signups if s["id"] == p1)["played_as"] == "Old#1111"


def test_the_history_carries_the_captain_seats(
    client: Client, seeded: dict[str, Any]
) -> None:
    p1, season_id = seeded["player_ids"][0], seeded["season_id"]
    with Session.begin() as session:
        session.add(
            DBTeamSeasonCaptain(
                team_id=seeded["team_a_id"], season_id=season_id, user_id=p1
            )
        )

    history = client.get(f"/users/{p1}/history").json()

    assert history["captain_of"] == [
        {"season_id": season_id, "team_id": seeded["team_a_id"], "team_name": "Alpha"}
    ]


def _match(match_id: str, tag: str, won: bool, mmr: int) -> W3CLadderMatchCreate:
    return W3CLadderMatchCreate(
        w3c_match_id=match_id,
        wc3_season=25,
        start_time=datetime(2026, 1, 10, 12, tzinfo=UTC),
        duration_s=900,
        race=Race.HU,
        played_race=Race.HU,
        won=won,
        mmr_before=mmr - 10,
        mmr_after=mmr,
        battleTag=tag,
    )


def test_the_sync_reads_every_tag_and_the_mmr_is_the_active_ones(
    seeded: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    p1 = seeded["player_ids"][0]
    smurf_id = second_tag(p1)
    by_tag = {
        "p1#1111": [_match("a" * 24, "P1#1111", True, 1500)],
        "smurf#2222": [_match("b" * 24, "Smurf#2222", False, 2100)],
    }
    asked: list[str] = []

    def matches(
        self: W3CService, tag: str, wanted: object
    ) -> tuple[list[W3CLadderMatchCreate], dict[int, bool]]:
        asked.append(tag)
        return by_tag[tag.lower()], {25: True}

    monkeypatch.setattr(W3CService, "current_season", lambda self: 25)
    monkeypatch.setattr(W3CService, "get_player_matches", matches)
    monkeypatch.setattr(UserService, "update_w3c_stats", lambda self, user: None)

    service = LadderService()
    result = service.sync_users(
        [UserReduced(id=p1, name="P1", battleTag="P1#1111")],
        datetime(2026, 1, 1, tzinfo=UTC),
        [25],
    )

    assert result.synced == [p1]
    assert asked == ["P1#1111", "Smurf#2222"]
    with Session() as session:
        stamped = {
            row.w3c_match_id[0]: row.battle_tag_id
            for row in session.scalars(
                select(W3CLadderMatch).where(col(W3CLadderMatch.user_id) == p1)
            )
        }
        active = session.scalars(
            select(col(UserBattleTag.id)).where(
                col(UserBattleTag.user_id) == p1, col(UserBattleTag.is_active)
            )
        ).one()
    assert stamped == {"a": active, "b": smurf_id}

    ladder = service.user_ladder(p1)
    assert (ladder.games, ladder.wins, ladder.losses) == (2, 1, 1)
    assert ladder.mmr.current == 1500
