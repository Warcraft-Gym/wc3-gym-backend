"""A season's phase derives from its series and gates the public signup.

Open until a series is scored or past its time, commenced from then on,
complete once every series has a result, overdue past the end date while a
result is missing. A signup to a season that is not open saves the profile
and answers closed; an admin adds the player, or does not.
"""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx2 import Client

from app.core.db import Session
from app.models.relationships import DBUserSeasonSignup
from app.models.season import Season, SeasonPublic
from tests.test_fantasy_locks import schedule, score
from tests.test_player_session import SIGNUP_BODY


@pytest.fixture
def signup_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.users import UserService

    monkeypatch.setattr(UserService, "validate_battle_tag", lambda self, tag: True)
    monkeypatch.setattr(UserService, "update_w3c_stats_by_id", lambda self, uid: None)


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
    client: Client,
    seeded: dict[str, Any],
    signup_ready: None,
    member: Callable[..., dict[str, str]],
) -> None:
    headers = member("99")
    resp = client.post("/signup", json=SIGNUP_BODY, headers=headers)
    assert resp.status_code == 201, resp.text
    assert resp.json()["signup"] == "closed"
    assert "no guarantee" in resp.json()["message"]
    with Session() as session:
        key = {"user_id": resp.json()["id"], "season_id": seeded["season_id"]}
        assert session.get(DBUserSeasonSignup, key) is None

    # The same form on an open season lands in the season
    score(seeded["series_played_id"], None, None)
    schedule(seeded["series_played_id"], None)
    resp = client.post("/signup", json=SIGNUP_BODY, headers=headers)
    assert resp.status_code == 201, resp.text
    assert "signup" not in resp.json()
    with Session() as session:
        assert session.get(DBUserSeasonSignup, key) is not None


def test_the_season_signups_open_flag_gates_the_season_not_the_profile(
    client: Client,
    seeded: dict[str, Any],
    signup_ready: None,
    member: Callable[..., dict[str, str]],
    auth_headers: dict[str, str],
) -> None:
    score(seeded["series_played_id"], None, None)
    schedule(seeded["series_played_id"], None)
    assert phase(client, seeded["season_id"]) == "open"

    def switch(value: bool) -> None:
        resp = client.put(
            f"/seasons/{seeded['season_id']}",
            json={"signups_open": value},
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text
        assert resp.json()["signups_open"] is value

    # Off: the profile edit saves, the open season takes a request only
    switch(False)
    headers = member("99")
    resp = client.post("/signup", json=SIGNUP_BODY | {"country": "SE"}, headers=headers)
    assert resp.status_code == 201, resp.text
    assert resp.json()["signup"] == "closed"
    assert client.get(f"/users/{resp.json()['id']}").json()["country"] == "SE"
    key = {"user_id": resp.json()["id"], "season_id": seeded["season_id"]}
    with Session() as session:
        assert session.get(DBUserSeasonSignup, key) is None

    # On: the same form saves the profile and lands in the season
    switch(True)
    resp = client.post("/signup", json=SIGNUP_BODY | {"country": "NO"}, headers=headers)
    assert resp.status_code == 201, resp.text
    assert "signup" not in resp.json()
    assert client.get(f"/users/{resp.json()['id']}").json()["country"] == "NO"
    with Session() as session:
        assert session.get(DBUserSeasonSignup, key) is not None


@pytest.mark.parametrize(
    "build",
    [
        SeasonPublic.from_season,
        SeasonPublic.from_season_reduced,
        SeasonPublic.from_season_without_maps,
    ],
)
def test_every_season_answer_carries_the_flags_and_the_window(
    build: Callable[..., Any],
) -> None:
    season = Season(
        id=1,
        name="Cup",
        series_per_round=1,
        signups_open=False,
        scheduling_enabled=False,
        checkin_days=5,
    )
    public = build(season)
    assert (public.signups_open, public.scheduling_enabled) == (False, False)
    assert public.checkin_days == 5
