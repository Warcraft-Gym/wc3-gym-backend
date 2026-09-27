"""Pin every career answer of a mixed league against tests/data/career_parity.json.

The league holds five seasons, one of them empty, historical baselines, rows
with and without a user, rows that find their player by name, a player two
rows claim, a name another row already claimed, and players who hold no row.
Every sort key runs both ways, with and without a search, and every page of
the list walks the same order.

Set UPDATE_CAREER_SNAPSHOT=1 to write the file again, and read the diff.
"""

import json
import os
import random
from datetime import date, datetime
from pathlib import Path
from typing import Any, get_args

import pytest
from httpx2 import Client
from sqlalchemy import BigInteger, literal, select
from sqlalchemy.dialects.postgresql.psycopg import PGDialect_psycopg

from app.core import career
from app.core.db import Session
from app.models.base import ident
from app.models.enums import Race
from app.models.league import League
from app.models.match import Match
from app.models.player_career_stats import PlayerCareerStats
from app.models.season import Season
from app.models.series import Series
from app.models.team import Team
from app.models.user import User
from app.services.derived import CareerSort
from app.services.player_career_stats import PlayerCareerStatsService
from tests.seed import active

SNAPSHOT = Path(__file__).parent / "data" / "career_parity.json"


def test_rating_truncates_the_exact_weighted_sum() -> None:
    """A float fold can land just below an integer at this boundary."""
    seasons = [1]
    assert career.rating(1940, {1: 1.5}, seasons) == 1899
    with Session.begin() as session:
        score = career.season_score_sql(literal(1), literal(2), literal(1), seasons)
        sql_rating = career.rating_sql(literal(1940), score, seasons)
        assert session.scalar(select(sql_rating)) == 1899
    compiled = select(sql_rating).compile(dialect=PGDialect_psycopg())
    large_values = {career.SCALE, career.decay_weight(1)}
    large_binds = [
        bind for bind in compiled.binds.values() if bind.value in large_values
    ]
    assert {bind.value for bind in large_binds} == large_values
    assert all(isinstance(bind.type, BigInteger) for bind in large_binds)


NAMES = (
    "Alpha",
    "Bravo",
    "Charlie",
    "Delta",
    "Echo",
    "Foxtrot",
    "Golf",
    "Hotel",
    "India",
    "juliet",
    "Kilo",
    "Lima",
    "Mike_2",
    "Oscar%",
    "Papa",
)

# Who plays each season; season 3 holds no series at all
ROSTERS = {
    1: ("Alpha", "Bravo", "Charlie", "Delta", "Golf", "Hotel"),
    2: ("Alpha", "Bravo", "Delta", "Foxtrot", "India", "juliet", "Golf"),
    3: (),
    4: ("Alpha", "Charlie", "Foxtrot", "India", "juliet", "Mike_2", "Oscar%"),
    5: ("Bravo", "Charlie", "Delta", "Hotel", "Mike_2", "Oscar%", "Alpha"),
}

# Kilo and Papa stand only in series that were never played
UNPLAYED = (("Kilo", "Papa", 2), ("Papa", "Kilo", 5))

SCORES = ((2, 0), (2, 1), (1, 2), (0, 2), (0, 0), (None, None), (1, 1))

# player name, user name, then the historical rating, series won and lost,
# maps won and lost, and seasons played
ROWS: tuple[tuple[str, str | None, int | None, int, int, int, int, int], ...] = (
    ("Alpha", "Alpha", 500, 10, 5, 25, 15, 3),
    # names no user, so the player name links Bravo
    ("Bravo", None, 300, 6, 6, 15, 15, 2),
    # Echo never played a series
    ("Echo", "Echo", 1000, 20, 2, 45, 10, 4),
    ("Charlie old", "Charlie", 200, 3, 3, 7, 7, 1),
    # Charlie's own row claims him first, so this row finds no player
    ("Charlie", None, 150, 2, 1, 4, 3, 1),
    # Lima never played, so the row name links Delta
    ("Delta", "Lima", 0, 1, 1, 2, 2, 1),
    ("Nobody", None, -50, 4, 4, 9, 9, 2),
    ("Foxtrot", "Foxtrot", None, 0, 0, 0, 0, 0),
    # a second row of the same user takes the same tally
    ("Foxtrot alt", "Foxtrot", 100, 1, 0, 2, 0, 1),
    # the name match holds case, so this row finds no player
    ("kilo", None, 50, 0, 1, 1, 2, 1),
    ("Kilo", None, 75, 1, 1, 3, 3, 1),
    ("Hotel", None, 250, 5, 2, 11, 6, 2),
)

SEARCHES = ("", "a", "CHAR", "_", "%", "zzz")


def row_key(row: dict[str, Any]) -> str:
    return str(row["id"]) if row["id"] is not None else f"user {row['user_id']}"


@pytest.fixture
def mixed_league() -> dict[str, int]:
    """The league of the module docstring, the same on every run."""
    pick = random.Random(17)
    with Session() as session:
        owner = League(name="Parity League")
        session.add(owner)
        session.flush()
        users = {
            name: User(
                name=name,
                battle_tags=active(f"{name}#{1000 + number}"),
                discordTag=name.lower(),
                discordId=str(100 + number),
                race=Race.HU,
                mmr=1500 + number,
            )
            for number, name in enumerate(NAMES)
        }
        seasons = {
            number: Season(
                name=f"Season {number}",
                league_id=ident(owner),
                series_per_round=2,
                start_date=date(2020 + number, 1, 6),
                end_date=date(2020 + number, 3, 6),
            )
            for number in ROSTERS
        }
        teams = [Team(name=f"T{n}", league_id=ident(owner)) for n in range(2)]
        session.add_all([*users.values(), *seasons.values(), *teams])
        session.flush()
        matches = {
            number: Match(
                team1_id=ident(teams[0]),
                team2_id=ident(teams[1]),
                season_id=ident(season),
                playday=1,
            )
            for number, season in seasons.items()
        }
        session.add_all(matches.values())
        session.flush()

        def add(one: str, two: str, own: int | None, opp: int | None, n: int) -> None:
            session.add(
                Series(
                    match_id=ident(matches[n]),
                    date_time=datetime(2026, 1, 7, 19, 0),
                    player1_id=ident(users[one]),
                    player2_id=ident(users[two]),
                    player1_score=own,
                    player2_score=opp,
                    host_player_id=ident(users[one]),
                )
            )

        for number, roster in ROSTERS.items():
            for index, one in enumerate(roster):
                for two in roster[index + 1 :]:
                    if pick.random() < 0.6:
                        add(one, two, *pick.choice(SCORES), number)
        for one, two, number in UNPLAYED:
            add(one, two, 0, 0, number)

        for name, user, rating, won, lost, maps_won, maps_lost, played in ROWS:
            session.add(
                PlayerCareerStats(
                    user_id=users[user].id if user else None,
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
        return {name: ident(user) for name, user in users.items()}


def answers(client: Client, users: dict[str, int]) -> dict[str, Any]:
    """Every career answer the snapshot pins."""
    listed = client.get("/stats/career")
    assert listed.status_code == 200
    rows = {row_key(row): row for row in listed.json()}

    orders: dict[str, Any] = {}
    for sort in (None, *get_args(CareerSort)):
        for order in ("asc", "desc"):
            for search in SEARCHES:
                url = f"/stats/career?order={order}&search={search.replace('%', '%25')}"
                if sort:
                    url += f"&sort={sort}"
                resp = client.get(url)
                assert resp.status_code == 200
                orders[f"{sort} {order} {search!r}"] = {
                    "total": resp.headers["X-Total-Count"],
                    "keys": [row_key(row) for row in resp.json()],
                }

    by_user = {}
    for name, user_id in users.items():
        resp = client.get(f"/stats/career/{user_id}")
        # Foxtrot holds two rows, and the route answers either one
        if name != "Foxtrot":
            by_user[name] = resp.json() if resp.status_code == 200 else None

    service = PlayerCareerStatsService()
    by_id = {}
    for key, row in rows.items():
        if row["id"] is not None:
            stat = service.get(row["id"])
            assert stat is not None
            by_id[key] = stat.to_dict()
    return {"rows": rows, "orders": orders, "by_user": by_user, "by_id": by_id}


def test_every_career_answer_matches_the_snapshot(
    client: Client, mixed_league: dict[str, int]
) -> None:
    payloads = answers(client, mixed_league)
    if os.getenv("UPDATE_CAREER_SNAPSHOT"):
        SNAPSHOT.write_text(json.dumps(payloads, indent=2, sort_keys=True) + "\n")
    assert payloads == json.loads(SNAPSHOT.read_text())


@pytest.mark.parametrize("sort", [None, "name", "rating", "games_winrate"])
@pytest.mark.parametrize("order", ["asc", "desc"])
@pytest.mark.parametrize("search", ["", "a"])
def test_every_page_walks_the_whole_order(
    client: Client,
    mixed_league: dict[str, int],
    sort: str | None,
    order: str,
    search: str,
) -> None:
    """Pages of three walk the same rows as one call, and each counts them all."""
    url = f"/stats/career?order={order}&search={search}"
    if sort:
        url += f"&sort={sort}"
    whole = client.get(url)
    total = whole.headers["X-Total-Count"]
    assert int(total) == len(whole.json())

    walked = []
    for offset in range(0, int(total) + 3, 3):
        page = client.get(f"{url}&limit=3&offset={offset}")
        assert page.status_code == 200
        assert page.headers["X-Total-Count"] == total
        walked += page.json()
    assert walked == whole.json()
