"""Series answers carry each side's signup race for the season of the match.

The race icon next to a series player must be the race the player registered
on for that season, not the profile race, which can change between seasons.
signup_race stays null when the season holds no signup for the player, and the
frontend falls back to the profile race then.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from httpx2 import Client

from app.models.enums import Race


@pytest.fixture
def league(app: FastAPI) -> dict[str, Any]:
    from app.core.db import Session
    from app.models.relationships import DBUserSeasonSignup
    from tests.seed import seed_league

    with Session.begin() as session:
        seeded = seed_league(session)
        # P1 registered on a race that differs from the profile (HU)
        session.add(
            DBUserSeasonSignup(
                user_id=seeded["player_ids"][0],
                season_id=seeded["season_id"],
                race=Race.UD,
            )
        )
    return seeded


def test_a_series_answer_carries_the_signup_race(
    client: Client, league: dict[str, Any]
) -> None:
    series = client.get(f"/series/{league['series_played_id']}").json()
    assert series["player1"]["signup_race"] == "UD"
    assert series["player1"]["race"] == "HU"
    # No signup row for player2: null, the profile race is the fallback
    assert series["player2"]["signup_race"] is None


def test_the_public_signup_stores_the_signup_race(
    client: Client, league: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A GNL season signup records the form's race on the signup row."""
    from app.api.routes.public import _token_store
    from app.core.db import Session
    from app.models.relationships import DBUserSeasonSignup
    from app.services.users import UserService

    monkeypatch.setattr(UserService, "validate_battle_tag", lambda self, tag: True)
    monkeypatch.setattr(UserService, "update_w3c_stats_by_id", lambda self, uid: None)
    _token_store["t"] = {
        "discord_id": "99",
        "discord_tag": "p9",
        "season_id": league["season_id"],
        "access_type": "signup",
        "expires_at": datetime.now(UTC) + timedelta(minutes=5),
    }
    resp = client.post(
        "/signup",
        json={"token": "t", "name": "P9", "battleTag": "P9#1234", "race": "NE"},
    )
    assert resp.status_code == 201, resp.text
    with Session() as session:
        signup = session.get(
            DBUserSeasonSignup,
            {"user_id": resp.json()["id"], "season_id": league["season_id"]},
        )
        assert signup is not None
        assert signup.race == Race.NE


def test_a_series_list_carries_the_signup_race(
    client: Client, league: dict[str, Any]
) -> None:
    season_id = league["season_id"]
    response = client.post(f"/series/season/{season_id}/playday/1/search")
    entries = {entry["id"]: entry for entry in response.json()}
    assert len(entries) == 2
    played = entries[league["series_played_id"]]
    assert played["player1"]["signup_race"] == "UD"
    assert played["player2"]["signup_race"] is None
    # Neither player of the open series signed up for the season
    open_series = entries[league["series_open_id"]]
    assert open_series["player1"]["signup_race"] is None
    assert open_series["player2"]["signup_race"] is None
