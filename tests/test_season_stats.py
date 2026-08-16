"""What SeriesService.calculateUserSeasonStats counts and in which order.

The counts come from the database, so the rules live in SQL: a series
counts as played once both scores are in and they are not both zero, and
the player who took two games won it.

matchup_history is stored as JSON, so its order is part of the stored
value. The order is playday then series id, which no longer depends on
the order the database hands the rows back.
"""

from datetime import datetime
from typing import Any

import pytest
from fastapi import FastAPI

from app.core.db import Session
from app.models.enums import Race
from app.models.match import Match
from app.models.series import Series
from app.models.user import User
from app.services.series import SeriesService


@pytest.fixture
def service() -> SeriesService:
    return SeriesService(score_app_service=None, user_app_service=None)


def add_series(**values: object) -> int:
    with Session() as session:
        series = Series(**values)
        session.add(series)
        session.commit()
        return series.id


def test_the_seeded_season_counts_one_win_and_one_open_series(
    app: FastAPI, seeded: dict[str, Any], service: SeriesService
) -> None:
    """Player 1 won 2-1; the second series has no scores, so it only counts
    as a game played."""
    stats = service.calculateUserSeasonStats(
        seeded["player_ids"][0], seeded["season_id"], seeded["team_a_id"]
    )
    assert (stats.games, stats.wins, stats.losses) == (1, 1, 0)
    assert stats.matchup_history == [Race.NE.value]

    opponent = service.calculateUserSeasonStats(
        seeded["player_ids"][2], seeded["season_id"], seeded["team_b_id"]
    )
    assert (opponent.games, opponent.wins, opponent.losses) == (1, 0, 1)
    assert opponent.matchup_history == [Race.HU.value]

    open_series = service.calculateUserSeasonStats(
        seeded["player_ids"][1], seeded["season_id"], seeded["team_a_id"]
    )
    assert (open_series.games, open_series.wins, open_series.losses) == (1, 0, 0)


def test_a_zero_to_zero_series_is_played_but_neither_won_nor_lost(
    app: FastAPI, seeded: dict[str, Any], service: SeriesService
) -> None:
    add_series(
        match_id=seeded["match_id"],
        player1_id=seeded["player_ids"][0],
        player2_id=seeded["player_ids"][2],
        player1_score=0,
        player2_score=0,
        host_player_id=seeded["player_ids"][0],
    )
    stats = service.calculateUserSeasonStats(
        seeded["player_ids"][0], seeded["season_id"], seeded["team_a_id"]
    )
    assert (stats.games, stats.wins, stats.losses) == (2, 1, 0)


def test_matchup_history_follows_playday_not_series_id(
    app: FastAPI, seeded: dict[str, Any], service: SeriesService
) -> None:
    """A series added later on an earlier playday comes first."""
    with Session() as session:
        later_playday = Match(
            team1_id=seeded["team_a_id"],
            team2_id=seeded["team_b_id"],
            season_id=seeded["season_id"],
            playday=2,
        )
        session.add(later_playday)
        session.commit()
        later_playday_id = later_playday.id

    # Playday 2 first, so its series carries the lower id
    add_series(
        match_id=later_playday_id,
        date_time=datetime(2026, 1, 14, 19, 0),
        player1_id=seeded["player_ids"][0],
        player2_id=seeded["player_ids"][2],
        player1_score=2,
        player2_score=0,
        host_player_id=seeded["player_ids"][0],
    )
    add_series(
        match_id=seeded["match_id"],
        player1_id=seeded["player_ids"][0],
        player2_id=seeded["player_ids"][3],
        player1_score=1,
        player2_score=2,
        host_player_id=seeded["player_ids"][0],
    )

    stats = service.calculateUserSeasonStats(
        seeded["player_ids"][0], seeded["season_id"], seeded["team_a_id"]
    )
    assert (stats.games, stats.wins, stats.losses) == (3, 2, 1)
    # Both playday 1 series, then the playday 2 one; id order reads NE NE UD
    assert stats.matchup_history == [Race.NE.value, Race.UD.value, Race.NE.value]


def test_a_player_with_no_series_in_the_season_counts_nothing(
    app: FastAPI, seeded: dict[str, Any], service: SeriesService
) -> None:
    with Session() as session:
        stranger = User(
            name="P5",
            battleTag="P5#5555",
            discordTag="p5",
            discordId="5",
            race=Race.HU,
        )
        session.add(stranger)
        session.commit()
        stranger_id = stranger.id

    stats = service.calculateUserSeasonStats(
        stranger_id, seeded["season_id"], seeded["team_a_id"]
    )
    assert (stats.games, stats.wins, stats.losses) == (0, 0, 0)
    assert stats.matchup_history == []
