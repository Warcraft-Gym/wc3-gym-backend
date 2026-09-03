"""A season's phase derives from its series and gates the public signup.

Open until a series is scored or past its time, commenced from then on,
complete once every series has a result, overdue past the end date while a
result is missing. A signup to a season that is not open saves the profile
and answers closed; an admin adds the player, or does not.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx2 import Client

from app.core.db import Session
from app.models.relationships import DBUserSeasonSignup
from app.models.season import Season
from tests.test_fantasy_locks import schedule, score
from tests.test_public_token import SIGNUP_BODY, entry


@pytest.fixture
def signup_ready(monkeypatch: pytest.MonkeyPatch) -> dict[str, dict[str, Any]]:
    from app.api.routes.public import _token_store
    from app.services.users import UserService

    monkeypatch.setattr(UserService, "validate_battle_tag", lambda self, tag: True)
    monkeypatch.setattr(UserService, "update_w3c_stats_by_id", lambda self, uid: None)
    _token_store.clear()
    return _token_store


def phase(client: Client, season_id: int) -> str:
    return client.get(f"/seasons/{season_id}").json()["phase"]


def unscored(client: Client, season_id: int) -> int:
    return client.get(f"/seasons/{season_id}").json()["unscored_series"]


def end_on(season_id: int, days_from_now: int) -> None:
    with Session.begin() as session:
        season = session.get(Season, season_id)
        assert season is not None
        season.end_date = (datetime.now(UTC) + timedelta(days=days_from_now)).date()


def test_the_phase_follows_the_series(client: Client, seeded: dict[str, Any]) -> None:
    played, open_ = seeded["series_played_id"], seeded["series_open_id"]
    end_on(seeded["season_id"], 7)
    assert phase(client, seeded["season_id"]) == "commenced"

    score(played, None, None)
    schedule(played, datetime.now(UTC) + timedelta(days=1))
    assert phase(client, seeded["season_id"]) == "open"

    # A time in the past commences it; a series without a result never completes it
    schedule(played, datetime.now(UTC) - timedelta(hours=1))
    assert phase(client, seeded["season_id"]) == "commenced"
    score(open_, 2, 0)
    assert phase(client, seeded["season_id"]) == "commenced"

    # Past the end date the missing result makes it overdue; the result completes it
    end_on(seeded["season_id"], -1)
    assert phase(client, seeded["season_id"]) == "overdue"
    assert unscored(client, seeded["season_id"]) == 1
    score(played, 2, 1)
    assert phase(client, seeded["season_id"]) == "complete"
    assert unscored(client, seeded["season_id"]) == 0

    listed = {s["id"]: s["phase"] for s in client.get("/seasons").json()}
    assert listed[seeded["season_id"]] == "complete"


def test_a_signup_to_a_commenced_season_saves_the_profile_only(
    client: Client, seeded: dict[str, Any], signup_ready: dict[str, dict[str, Any]]
) -> None:
    signup_ready["t"] = entry() | {
        "discord_id": "99",
        "season_id": str(seeded["season_id"]),
    }
    resp = client.post("/signup", json={"token": "t"} | SIGNUP_BODY)
    assert resp.status_code == 201, resp.text
    assert resp.json()["signup"] == "closed"
    assert "no guarantee" in resp.json()["message"]
    with Session() as session:
        key = {"user_id": resp.json()["id"], "season_id": seeded["season_id"]}
        assert session.get(DBUserSeasonSignup, key) is None

    # The same form on an open season lands in the season
    score(seeded["series_played_id"], None, None)
    schedule(seeded["series_played_id"], None)
    signup_ready["t"] = entry() | {
        "discord_id": "99",
        "season_id": str(seeded["season_id"]),
    }
    resp = client.post("/signup", json={"token": "t"} | SIGNUP_BODY)
    assert resp.status_code == 201, resp.text
    assert "signup" not in resp.json()
    with Session() as session:
        assert session.get(DBUserSeasonSignup, key) is not None
