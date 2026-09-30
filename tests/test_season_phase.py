"""A season's phase is derived on every read and gates the public signup.

Open until a series is scored or past its time, commenced from then on,
overdue past the end date, complete once an admin closed it. A signup to a
season that is not open saves the profile and answers closed; an admin adds
the player, or does not.
"""

from collections.abc import Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from httpx2 import Client

from app.core.db import Session
from app.models.relationships import DBTeamSeasonCaptain, DBUserSeasonSignup
from app.models.season import Season, SeasonPublic
from app.services.maps import MapService
from app.services.seasons import SeasonService
from app.services.teams import TeamService
from app.services.users import UserService
from tests.test_fantasy_locks import schedule, score
from tests.test_player_session import SIGNUP_BODY


@pytest.fixture
def signup_ready(monkeypatch: pytest.MonkeyPatch) -> None:
    from app.services.users import UserService

    monkeypatch.setattr(UserService, "validate_battle_tag", lambda self, tag: True)
    monkeypatch.setattr(UserService, "update_w3c_stats_by_id", lambda self, uid: None)


def seasons() -> SeasonService:
    return SeasonService(user_app_service=UserService(), map_app_service=MapService())


def phase(season_id: int) -> str | None:
    return seasons().get(season_id).phase


def unscored(season_id: int) -> int | None:
    return seasons().get(season_id).unscored_series


def end_on(season_id: int, days_from_now: int) -> None:
    with Session.begin() as session:
        season = session.get(Season, season_id)
        assert season is not None
        season.end_date = (datetime.now(UTC) + timedelta(days=days_from_now)).date()


def test_the_phase_follows_the_series_and_ends_on_the_close(
    client: Client, seeded: dict[str, Any], auth_headers: dict[str, str]
) -> None:
    played, open_ = seeded["series_played_id"], seeded["series_open_id"]
    end_on(seeded["season_id"], 7)
    assert phase(seeded["season_id"]) == "commenced"

    score(played, None, None)
    schedule(played, datetime.now(UTC) + timedelta(days=1))
    assert phase(seeded["season_id"]) == "open"

    # A time in the past commences it
    schedule(played, datetime.now(UTC) - timedelta(hours=1))
    assert phase(seeded["season_id"]) == "commenced"

    # Every series it holds being scored leaves the next round to draft
    score(open_, 2, 0)
    score(played, 2, 1)
    assert phase(seeded["season_id"]) == "commenced"
    assert unscored(seeded["season_id"]) == 0

    # Past the end date it is overdue, with or without a result missing
    end_on(seeded["season_id"], -1)
    assert phase(seeded["season_id"]) == "overdue"
    score(played, None, None)
    assert phase(seeded["season_id"]) == "overdue"
    assert unscored(seeded["season_id"]) == 1

    # Only the close completes it, and it keeps the count of the missing result
    path = f"/events/{seeded['season_id']}"
    assert client.post(f"{path}/finish", headers=auth_headers).status_code == 200
    assert phase(seeded["season_id"]) == "complete"
    assert unscored(seeded["season_id"]) == 1
    listed = {season.id: season.phase for season in seasons().get_all()}
    assert listed[seeded["season_id"]] == "complete"

    assert client.post(f"{path}/reopen", headers=auth_headers).status_code == 200
    assert phase(seeded["season_id"]) == "overdue"


def test_a_captain_keeps_the_seat_until_the_season_is_closed(
    client: Client, seeded: dict[str, Any], auth_headers: dict[str, str]
) -> None:
    """Every series scored leaves the next round to draft, so the seat stands."""
    season_id = seeded["season_id"]
    seat = (seeded["team_a_id"], season_id)
    with Session.begin() as session:
        session.add(
            DBTeamSeasonCaptain(
                team_id=seat[0], season_id=season_id, user_id=seeded["player_ids"][0]
            )
        )
    teams = TeamService(user_app_service=UserService())
    score(seeded["series_open_id"], 2, 0)
    assert teams.captain_seats("1") == [seat]

    closed = client.post(f"/events/{season_id}/finish", headers=auth_headers)
    assert closed.status_code == 200, closed.text
    assert teams.captain_seats("1") == []


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
    assert phase(seeded["season_id"]) == "open"

    def switch(value: bool) -> None:
        resp = client.put(
            f"/events/{seeded['season_id']}",
            json={"signups_open": value},
            headers=auth_headers,
        )
        assert resp.status_code == 200, resp.text

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


def test_the_season_answer_carries_the_flags_and_the_window() -> None:
    season = Season(
        id=1,
        name="Cup",
        series_per_round=1,
        signups_open=False,
        scheduling_enabled=False,
        checkin_days=5,
    )
    public = SeasonPublic.from_season(season)
    assert (public.signups_open, public.scheduling_enabled) == (False, False)
    assert public.checkin_days == 5
