"""The career totals come from the historical baseline and the map scores.

The stored recalculation and the derived read answer the same numbers, so
these tests run the recalculation first and then compare the answer of the
read path with the stored columns it no longer reads. Both paths run in the
same test, over the same database.

A player who has played and holds no stored row stands in the list as well,
which the stored path could only do after someone pressed the button.
"""

import json
from datetime import date, datetime
from typing import Any

import pytest
from httpx2 import Client
from sqlalchemy import select

from app.core.db import Session
from app.models.enums import Race
from app.models.match import Match
from app.models.player_career_stats import (
    PlayerCareerStats,
    PlayerCareerStatsPublic,
)
from app.models.season import Season
from app.models.series import Series
from app.models.team import Team
from app.models.user import User

# Ids, scores and season of every series of the league, by player name
RESULTS = [
    ("Alpha", "Charlie", 2, 0, 0),
    ("Bravo", "Delta", 1, 2, 0),
    ("Alpha", "Delta", 2, 1, 1),
    ("Bravo", "Charlie", 0, 2, 1),
    ("Charlie", "Delta", None, None, 1),
]

# player name, then the historical rating, series won and lost, maps won and
# lost, and seasons played the CSV import left behind
BASELINES = [
    ("Alpha", 500, 10, 5, 25, 15, 3),
    ("Bravo", 300, 6, 6, 15, 15, 2),
    ("Echo", 1000, 20, 2, 45, 10, 4),
]


@pytest.fixture
def league(client: Client) -> dict[str, Any]:
    """Five players over two seasons, and the three kinds of stored row.

    Alpha holds a historical row that names his user, Bravo holds one that
    names no user and only matches him by name, and Echo holds one and has
    never played a series. Charlie and Delta hold no row at all.
    """
    with Session() as session:
        players = {
            name: User(
                name=name,
                battleTag=f"{name}#1000",
                discordTag=name.lower(),
                discordId=str(number),
                race=Race.HU,
                mmr=1500,
            )
            for number, name in enumerate(
                ("Alpha", "Bravo", "Charlie", "Delta", "Echo")
            )
        }
        seasons = [
            Season(
                name=f"Season {number}",
                number_weeks=4,
                series_per_week=2,
                start_date=date(2025 + number, 1, 6),
                end_date=date(2025 + number, 3, 6),
            )
            for number in (1, 2)
        ]
        teams = [Team(name="One"), Team(name="Two")]
        session.add_all([*players.values(), *seasons, *teams])
        session.flush()

        matches = [
            Match(
                team1_id=teams[0].id,
                team2_id=teams[1].id,
                season_id=season.id,
                playday=1,
            )
            for season in seasons
        ]
        session.add_all(matches)
        session.flush()

        for one, two, own, opp, season in RESULTS:
            session.add(
                Series(
                    match_id=matches[season].id,
                    date_time=datetime(2026, 1, 7, 19, 0),
                    player1_id=players[one].id,
                    player2_id=players[two].id,
                    player1_score=own,
                    player2_score=opp,
                    host_player_id=players[one].id,
                )
            )

        for name, rating, won, lost, maps_won, maps_lost, played in BASELINES:
            # Bravo's row names no user, so only his player name links him
            user_id = players[name].id if name != "Bravo" else None
            session.add(
                PlayerCareerStats(
                    user_id=user_id,
                    player_name=name,
                    historical_rating=rating,
                    historical_series_won=won,
                    historical_series_lost=lost,
                    historical_games_won=maps_won,
                    historical_games_lost=maps_lost,
                    historical_seasons_played=played,
                )
            )
        session.commit()
        return {name: player.id for name, player in players.items()}


def stored_page(limit: int | None = None, offset: int = 0) -> tuple[str, int]:
    """The answer the stored columns give, as the read path built it.

    The rating orders the rows and the id breaks a tie.
    """
    with Session() as session:
        stats = (
            session.scalars(
                select(PlayerCareerStats)
                .options(*PlayerCareerStats.eager_options())
                .order_by(PlayerCareerStats.rating.desc(), PlayerCareerStats.id)
            )
            .unique()
            .all()
        )
        rows = [
            PlayerCareerStatsPublic.from_career_stats(stat).to_dict() for stat in stats
        ]
    end = None if limit is None else offset + limit
    return json.dumps(rows[offset:end]), len(rows)


def recalculate(client: Client, headers: dict[str, str]) -> None:
    resp = client.post("/stats/career/recalculate", headers=headers)
    assert resp.status_code == 200, resp.text


def test_the_derived_list_equals_the_stored_one(
    client: Client, auth_headers: dict[str, str], league: dict[str, int]
) -> None:
    """The full list, byte for byte, over both code paths."""
    recalculate(client, auth_headers)
    stored, total = stored_page()

    resp = client.get("/stats/career")
    assert resp.status_code == 200
    assert resp.headers["X-Total-Count"] == str(total)
    assert json.dumps(resp.json()) == stored

    ratings = [row["rating"] for row in resp.json()]
    assert len(set(ratings)) == len(ratings), "the order must not rest on a tie"
    assert len(ratings) == 5


def test_the_derived_page_equals_the_stored_one(
    client: Client, auth_headers: dict[str, str], league: dict[str, int]
) -> None:
    """One page of two rows, and the total the header carries."""
    recalculate(client, auth_headers)
    stored, total = stored_page(limit=2, offset=2)

    resp = client.get("/stats/career?limit=2&offset=2")
    assert resp.status_code == 200
    assert resp.headers["X-Total-Count"] == str(total)
    assert json.dumps(resp.json()) == stored


def test_the_derived_player_equals_the_stored_one(
    client: Client, auth_headers: dict[str, str], league: dict[str, int]
) -> None:
    """One player, read by his user id."""
    recalculate(client, auth_headers)
    stored, _ = stored_page()
    alpha = next(row for row in json.loads(stored) if row["player_name"] == "Alpha")

    resp = client.get(f"/stats/career/{league['Alpha']}")
    assert resp.status_code == 200
    assert json.dumps(resp.json()) == json.dumps(alpha)


def test_the_unmapped_historical_row_takes_the_series_of_its_name(
    client: Client, auth_headers: dict[str, str], league: dict[str, int]
) -> None:
    """Bravo's row names no user, and still counts the series he played."""
    rows = client.get("/stats/career").json()
    bravo = next(row for row in rows if row["player_name"] == "Bravo")
    # Two historical losses more than the baseline, and one season more
    assert bravo["series_lost"] == 8
    assert bravo["seasons_played"] == 4
    assert bravo["user_id"] is None


def test_a_player_with_no_stored_row_stands_in_the_list(
    client: Client, seeded: dict[str, Any]
) -> None:
    """P3 played a series and holds no career row, so the list derives one."""
    resp = client.get("/stats/career")
    assert resp.status_code == 200
    rows = resp.json()
    assert resp.headers["X-Total-Count"] == "3"

    derived = next(row for row in rows if row["player_name"] == "P3")
    assert derived["id"] is None
    assert derived["historical_rating"] is None
    assert derived["user"]["battleTag"] == "P3#3333"
    # P3 lost the played series 1-2, and P4 has played nothing at all
    assert derived["series_lost"] == 1
    assert derived["games_won"] == 1
    assert derived["seasons_played"] == 1
    assert [row["player_name"] for row in rows if row["player_name"] == "P4"] == []
