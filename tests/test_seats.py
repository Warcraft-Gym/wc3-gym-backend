"""A captain holds their powers in every season they captain until it completes.

Two seasons run at once, so a captain of team X in one and team Y in the other
carries both seats. A season with every series scored carries none.
"""

from datetime import date, datetime
from typing import Any

import pytest
from httpx2 import Client

from tests.test_discord_auth import ACCOUNT, SESSION, stub_clerk
from tests.test_player_session import (  # noqa: F401
    SIGNUP_BODY,
    member_session,
    w3c_free,
)


def _add_season(name: str, *, complete: bool, seeded: dict[str, Any]) -> int:
    """A second season over the same teams. A complete one has its series scored."""
    from app.core.db import Session
    from app.models.base import ident
    from app.models.match import Match
    from app.models.series import Series
    from app.models.team_season import DBTeamSeason
    from app.models.user_team_season import DBUserTeamSeason
    from tests.seed import add_season

    with Session.begin() as session:
        season = add_season(
            session,
            2,
            name=name,
            series_per_round=1,
            start_date=date(2026, 3, 2),
            end_date=date(2026, 12, 31),
        )
        season_id = ident(season)
        session.add_all(
            [
                DBTeamSeason(team_id=seeded["team_a_id"], season_id=season_id),
                DBTeamSeason(team_id=seeded["team_b_id"], season_id=season_id),
                DBUserTeamSeason(
                    user_id=seeded["player_ids"][0],
                    team_id=seeded["team_a_id"],
                    season_id=season_id,
                ),
            ]
        )
        match = Match(
            team1_id=seeded["team_a_id"],
            team2_id=seeded["team_b_id"],
            season_id=season_id,
            playday=1,
        )
        session.add(match)
        session.flush()
        if complete:
            session.add(
                Series(
                    match_id=ident(match),
                    date_time=datetime(2026, 3, 4, 19, 0),
                    player1_id=seeded["player_ids"][0],
                    player2_id=seeded["player_ids"][2],
                    player1_score=2,
                    player2_score=0,
                    host_player_id=seeded["player_ids"][0],
                )
            )
        return season_id


def _captain(team_id: int, season_id: int, user_id: int) -> None:
    """One captain row, written the way the admin page writes it."""
    from app.core.db import Session
    from app.models.relationships import DBTeamSeasonCaptain

    with Session.begin() as session:
        session.add(
            DBTeamSeasonCaptain(team_id=team_id, season_id=season_id, user_id=user_id)
        )


@pytest.fixture
def p1(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """P1's signed-in session, with no bot token so no role sync runs."""
    monkeypatch.delenv("DISCORD_BOT_TOKEN", raising=False)
    return member_session(monkeypatch)


def test_a_captain_of_a_complete_season_is_only_a_member(
    client: Client, seeded: dict[str, Any], p1: dict[str, str]
) -> None:
    """Every series of that season is scored, so the seat carries nothing."""
    done = _add_season("Season done", complete=True, seeded=seeded)
    _captain(seeded["team_a_id"], done, seeded["player_ids"][0])

    me = client.get("/me", headers=p1).json()

    assert me["role"] == "member"
    assert me["seats"] == []


def test_a_captain_of_two_running_seasons_holds_both_seats(
    client: Client, seeded: dict[str, Any], p1: dict[str, str]
) -> None:
    later = _add_season("Season next", complete=False, seeded=seeded)
    _captain(seeded["team_a_id"], seeded["season_id"], seeded["player_ids"][0])
    _captain(seeded["team_b_id"], later, seeded["player_ids"][0])

    me = client.get("/me", headers=p1).json()

    assert me["role"] == "captain"
    # newest season first
    assert me["seats"] == [
        {"team_id": seeded["team_b_id"], "season_id": later},
        {"team_id": seeded["team_a_id"], "season_id": seeded["season_id"]},
    ]


def test_the_availability_guard_reads_the_pair_not_the_team(
    client: Client, seeded: dict[str, Any], p1: dict[str, str]
) -> None:
    """The same team in a season the captain does not hold is refused."""
    later = _add_season("Season next", complete=False, seeded=seeded)
    _captain(seeded["team_a_id"], seeded["season_id"], seeded["player_ids"][0])

    path = f"/teams/{seeded['team_a_id']}/seasons"
    refused = client.get(f"{path}/{later}/availability", headers=p1)
    assert refused.status_code == 403, refused.text
    assert refused.json() == {"error": "Not your team"}

    held = client.get(f"{path}/{seeded['season_id']}/availability", headers=p1)
    assert held.status_code == 200, held.text


def test_the_draft_guard_reads_the_pair_not_the_team(
    client: Client, seeded: dict[str, Any], p1: dict[str, str]
) -> None:
    """P1 captains Alpha in the later season only, so the seeded match is not his."""
    later = _add_season("Season next", complete=False, seeded=seeded)
    _captain(seeded["team_a_id"], later, seeded["player_ids"][0])
    body = {
        "match_id": seeded["match_id"],
        "player1_id": seeded["player_ids"][0],
        "player2_id": seeded["player_ids"][2],
        "host_player_id": seeded["player_ids"][0],
    }

    refused = client.post("/draft-series", json=body, headers=p1)
    assert refused.status_code == 403, refused.text

    _captain(seeded["team_a_id"], seeded["season_id"], seeded["player_ids"][0])
    allowed = client.post("/draft-series", json=body, headers=p1)
    assert allowed.status_code == 201, allowed.text


def test_view_as_seats_names_both_seats(
    client: Client, seeded: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """An admin debugging a captain lists the pairs in one header."""
    later = _add_season("Season next", complete=False, seeded=seeded)
    stub_clerk(monkeypatch, account={**ACCOUNT, "id": "220202568490418179"})
    viewing = SESSION | {
        "X-View-As": "captain",
        "X-View-Seats": (
            f"{seeded['team_a_id']}:{seeded['season_id']},"
            f"{seeded['team_b_id']}:{later},nonsense"
        ),
    }

    me = client.get("/me", headers=viewing).json()

    assert me["role"] == "captain"
    assert me["seats"] == [
        {"team_id": seeded["team_a_id"], "season_id": seeded["season_id"]},
        {"team_id": seeded["team_b_id"], "season_id": later},
    ]


def test_me_lists_every_running_season(
    client: Client,
    seeded: dict[str, Any],
    p1: dict[str, str],
    auth_headers: dict[str, str],
) -> None:
    """Newest first, with the signup and the roster team of each."""
    later = _add_season("Season next", complete=False, seeded=seeded)
    done = _add_season("Season done", complete=True, seeded=seeded)
    signed = client.post(
        f"/seasons/{seeded['season_id']}/signups",
        json={"user_ids": [seeded["player_ids"][0]], "race": "HU"},
        headers=auth_headers,
    )
    assert signed.status_code == 200, signed.text

    seasons = client.get("/me", headers=p1).json()["seasons"]

    assert [season["id"] for season in seasons] == [later, seeded["season_id"]]
    assert done not in [season["id"] for season in seasons]
    assert [season["signed_up"] for season in seasons] == [False, True]
    assert all(season["team"]["id"] == seeded["team_a_id"] for season in seasons)
    assert [season["captain"] for season in seasons] == [False, False]


def test_a_signup_lands_in_the_season_the_body_names(
    client: Client,
    seeded: dict[str, Any],
    p1: dict[str, str],
    w3c_free: None,  # noqa: F811
) -> None:
    """The newest season is the identity's own, so the body must win to reach the other."""
    later = _add_season("Season next", complete=False, seeded=seeded)
    _add_season("Season after", complete=False, seeded=seeded)

    resp = client.post("/signup", json=SIGNUP_BODY | {"season_id": later}, headers=p1)

    assert resp.status_code == 201, resp.text
    seasons = client.get("/me", headers=p1).json()["seasons"]
    assert [season["signed_up"] for season in seasons if season["id"] == later] == [
        True
    ]


def test_player_availability_writes_the_season_the_body_names(
    client: Client, seeded: dict[str, Any], p1: dict[str, str]
) -> None:
    _add_season("Season next", complete=False, seeded=seeded)

    resp = client.put(
        "/player-availability",
        json={"playday": 1, "available": False, "season_id": seeded["season_id"]},
        headers=p1,
    )

    assert resp.status_code == 200, resp.text
    read = client.get(
        "/player-series", params={"season_id": seeded["season_id"]}, headers=p1
    ).json()
    assert [row["playday"] for row in read["availability"]] == [1]


def test_player_series_answers_the_season_the_query_names(
    client: Client, seeded: dict[str, Any], p1: dict[str, str]
) -> None:
    later = _add_season("Season next", complete=False, seeded=seeded)

    body = client.get(
        "/player-series", params={"season_id": seeded["season_id"]}, headers=p1
    ).json()

    assert body["season_id"] == seeded["season_id"]
    assert len(body["rounds"]) == 4
    # without the parameter the identity's own season answers
    assert client.get("/player-series", headers=p1).json()["season_id"] == later
