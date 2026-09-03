"""Season answers carry the signup race of every player they name.

The race icon next to a player must be the race he registered on for that
season, not the profile race, which is a cosmetic default and can change
between seasons. signup_race stays null when the season holds no signup for
the player, and the frontend draws no icon then.
"""

from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from fastapi import FastAPI
from httpx2 import Client
from sqlmodel import select

from app.core.db import Session
from app.models.enums import Race
from app.models.relationships import DBFantasyTeamPlayer, DBUserSeasonSignup
from app.models.series import Series


@pytest.fixture
def league(app: FastAPI) -> dict[str, Any]:
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
    # No signup row for player2: null, and the page draws no icon
    assert series["player2"]["signup_race"] is None


def test_a_team_roster_carries_the_signup_race(
    client: Client, league: dict[str, Any]
) -> None:
    season_id = league["season_id"]
    teams = client.get(f"/teams/season/{season_id}").json()
    players = {
        player["id"]: player
        for team in teams
        for player in team["player_by_season"][str(season_id)]
    }
    assert players[league["player_ids"][0]]["signup_race"] == "UD"
    assert players[league["player_ids"][0]]["race"] == "HU"
    assert players[league["player_ids"][2]]["signup_race"] is None


def test_a_fantasy_team_carries_the_signup_race_of_its_players(
    client: Client, league: dict[str, Any]
) -> None:
    drafted = [league["player_ids"][0], league["player_ids"][2]]
    with Session.begin() as session:
        session.add_all(
            DBFantasyTeamPlayer(
                fantasy_team_id=league["fantasy_team_id"], user_id=user_id
            )
            for user_id in drafted
        )

    team = client.get(f"/fantasy/teams/{league['fantasy_team_id']}").json()
    assert {
        player["id"]: player["signup_race"] for player in team["drafted_players"]
    } == {drafted[0]: "UD", drafted[1]: None}


def test_a_ladder_season_row_reads_the_signup_race(
    client: Client, auth_headers: dict[str, str], league: dict[str, Any]
) -> None:
    """The ladder roster is the signups of the season, so a player who did not
    register stands nowhere on it."""
    body = client.get(
        f"/seasons/{league['season_id']}/ladder", headers=auth_headers
    ).json()
    rows = {
        player["id"]: player for team in body["teams"] for player in team["players"]
    }
    assert rows[league["player_ids"][0]]["race"] == "UD"
    assert league["player_ids"][2] not in rows


def test_the_public_signup_stores_the_signup_race(
    client: Client, league: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """A GNL season signup records the form's race on the signup row."""
    from app.api.routes.public import _token_store
    from app.services.users import UserService

    monkeypatch.setattr(UserService, "validate_battle_tag", lambda self, tag: True)
    monkeypatch.setattr(UserService, "update_w3c_stats_by_id", lambda self, uid: None)
    # Signups need an open season: no series scored or past its time
    with Session.begin() as session:
        for series in session.scalars(select(Series)):
            series.player1_score = series.player2_score = series.date_time = None
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


def test_a_draft_series_answer_carries_the_signup_race(
    league: dict[str, Any],
) -> None:
    from app.models.draft_series import DraftSeries
    from app.services.draft_series import DraftSeriesService

    with Session.begin() as session:
        session.add(
            DraftSeries(
                match_id=league["match_id"],
                player1_id=league["player_ids"][0],
                player2_id=league["player_ids"][2],
                host_player_id=league["player_ids"][0],
            )
        )
    drafts = DraftSeriesService().get_by_match_id(league["match_id"])
    assert drafts[0].player1 is not None
    assert drafts[0].player1.signup_race == "UD"
    assert drafts[0].player2 is not None
    assert drafts[0].player2.signup_race is None
