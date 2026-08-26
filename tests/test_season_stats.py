"""What app.services.derived counts for one player's season and in which order.

The counts come from the database: a series counts as a game once the
player stands in it, and pays a win or a loss once both map scores are in
and they are not both zero. The player who took two games won it.

matchup_history reads playday then series id, so the list follows the
order the season was played rather than the order the rows went in.
"""

from datetime import datetime
from typing import Any

import pytest
from fastapi import FastAPI
from httpx2 import Client

from app.core.db import Session
from app.models.enums import Race
from app.models.match import Match
from app.models.series import Series
from app.models.user import User, UserPublic
from app.models.user_team_season import UserTeamSeasonStatsPublic
from app.services import derived


def record(user_id: int, season_id: int) -> UserTeamSeasonStatsPublic:
    """The season record the API answers for one player."""
    stats = UserTeamSeasonStatsPublic(user_id=user_id, season_id=season_id)
    with Session() as session:
        derived.fill_gnl_stats(session, [UserPublic(gnl_stats=[stats])])
    return stats


def add_series(**values: object) -> int:
    with Session() as session:
        series = Series(**values)
        session.add(series)
        session.commit()
        return series.id


def test_the_seeded_season_counts_one_win_and_one_open_series(
    app: FastAPI, seeded: dict[str, Any]
) -> None:
    """Player 1 won 2-1; the second series has no scores, so it only counts
    as a game played."""
    stats = record(seeded["player_ids"][0], seeded["season_id"])
    assert (stats.games, stats.wins, stats.losses) == (1, 1, 0)
    assert stats.matchup_history == [Race.NE.value]

    opponent = record(seeded["player_ids"][2], seeded["season_id"])
    assert (opponent.games, opponent.wins, opponent.losses) == (1, 0, 1)
    assert opponent.matchup_history == [Race.HU.value]

    open_series = record(seeded["player_ids"][1], seeded["season_id"])
    assert (open_series.games, open_series.wins, open_series.losses) == (1, 0, 0)


def test_a_zero_to_zero_series_is_played_but_neither_won_nor_lost(
    app: FastAPI, seeded: dict[str, Any]
) -> None:
    add_series(
        match_id=seeded["match_id"],
        player1_id=seeded["player_ids"][0],
        player2_id=seeded["player_ids"][2],
        player1_score=0,
        player2_score=0,
        host_player_id=seeded["player_ids"][0],
    )
    stats = record(seeded["player_ids"][0], seeded["season_id"])
    assert (stats.games, stats.wins, stats.losses) == (2, 1, 0)


def test_matchup_history_follows_playday_not_series_id(
    app: FastAPI, seeded: dict[str, Any]
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

    stats = record(seeded["player_ids"][0], seeded["season_id"])
    assert (stats.games, stats.wins, stats.losses) == (3, 2, 1)
    # Both playday 1 series, then the playday 2 one; id order reads NE NE UD
    assert stats.matchup_history == [Race.NE.value, Race.UD.value, Race.NE.value]


def test_a_player_with_no_series_in_the_season_counts_nothing(
    app: FastAPI, seeded: dict[str, Any]
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

    stats = record(stranger_id, seeded["season_id"])
    assert (stats.games, stats.wins, stats.losses) == (0, 0, 0)
    assert stats.matchup_history == []


@pytest.mark.parametrize("route", ["user", "team"])
def test_an_imported_season_answers_the_record(
    client: Client, seeded: dict[str, Any], route: str
) -> None:
    """The seed writes the series rows the way a workbook import does, and
    both routes count the record off them."""
    user_id = seeded["player_ids"][0]
    season_id = seeded["season_id"]
    if route == "user":
        stats = client.get(f"/users/{user_id}").json()["gnl_stats"]
    else:
        teams = client.get(f"/teams/season/{season_id}").json()
        stats = next(
            player["gnl_stats"]
            for team in teams
            for player in team["player_by_season"][str(season_id)]
            if player["id"] == user_id
        )

    assert len(stats) == 1
    assert (stats[0]["games"], stats[0]["wins"], stats[0]["losses"]) == (1, 1, 0)
    assert stats[0]["matchup_history"] == [Race.NE.value]
