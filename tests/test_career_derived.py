"""The career totals come from the historical baseline and the map scores.

No column holds them, so these tests pin the whole answer: every field of
every row of the seeded league, in the order the rating puts them.

A player who has played and holds no stored row stands in the list as well,
which the stored path could only do after someone pressed the recalculate
button.
"""

from datetime import date, datetime
from typing import Any

import pytest
from httpx2 import Client

from app.core.db import Session
from app.models.enums import Race
from app.models.match import Match
from app.models.player_career_stats import PlayerCareerStats
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

PLAYERS = ("Alpha", "Bravo", "Charlie", "Delta", "Echo")


def player_block(name: str) -> dict[str, Any]:
    """The user object a career row carries. It holds no collection."""
    number = PLAYERS.index(name)
    return {
        "name": name,
        "battleTag": f"{name}#1000",
        "discordTag": name.lower(),
        "discordId": str(number),
        "mmr": 1500,
        "country": None,
        "fantasy_tier": None,
        "id": number + 1,
        "race": "HU",
        "w3c_synced_at": None,
        "ladder_synced_at": None,
    }


# Every field of every row, by rating, with the id as the tie-break
EXPECTED = [
    {
        "user_id": 1,
        "player_name": "Alpha",
        "historical_rating": 500,
        "historical_series_won": 10,
        "historical_series_lost": 5,
        "historical_games_won": 25,
        "historical_games_lost": 15,
        "historical_seasons_played": 3,
        "rating": 731,
        "series_won": 12,
        "series_lost": 5,
        "games_won": 29,
        "games_lost": 16,
        "seasons_played": 5,
        "id": 1,
        "user": player_block("Alpha"),
        "series_winrate": 70.59,
        "games_winrate": 64.44,
        "avg_series_per_season": 3.4,
    },
    {
        "user_id": 5,
        "player_name": "Echo",
        "historical_rating": 1000,
        "historical_series_won": 20,
        "historical_series_lost": 2,
        "historical_games_won": 45,
        "historical_games_lost": 10,
        "historical_seasons_played": 4,
        "rating": 722,
        "series_won": 20,
        "series_lost": 2,
        "games_won": 45,
        "games_lost": 10,
        "seasons_played": 4,
        "id": 3,
        "user": player_block("Echo"),
        "series_winrate": 90.91,
        "games_winrate": 81.82,
        "avg_series_per_season": 5.5,
    },
    {
        # Bravo's row names no user, so only his player name links him
        "user_id": None,
        "player_name": "Bravo",
        "historical_rating": 300,
        "historical_series_won": 6,
        "historical_series_lost": 6,
        "historical_games_won": 15,
        "historical_games_lost": 15,
        "historical_seasons_played": 2,
        "rating": 494,
        "series_won": 6,
        "series_lost": 8,
        "games_won": 16,
        "games_lost": 19,
        "seasons_played": 4,
        "id": 2,
        "user": None,
        "series_winrate": 42.86,
        "games_winrate": 45.71,
        "avg_series_per_season": 3.5,
    },
    {
        # Charlie holds no stored row, so the list derives one with a null id
        "user_id": 3,
        "player_name": "Charlie",
        "historical_rating": None,
        "historical_series_won": None,
        "historical_series_lost": None,
        "historical_games_won": None,
        "historical_games_lost": None,
        "historical_seasons_played": None,
        "rating": 327,
        "series_won": 1,
        "series_lost": 1,
        "games_won": 2,
        "games_lost": 2,
        "seasons_played": 2,
        "id": None,
        "user": player_block("Charlie"),
        "series_winrate": 50.0,
        "games_winrate": 50.0,
        "avg_series_per_season": 1.0,
    },
    {
        "user_id": 4,
        "player_name": "Delta",
        "historical_rating": None,
        "historical_series_won": None,
        "historical_series_lost": None,
        "historical_games_won": None,
        "historical_games_lost": None,
        "historical_seasons_played": None,
        "rating": 320,
        "series_won": 1,
        "series_lost": 1,
        "games_won": 3,
        "games_lost": 3,
        "seasons_played": 2,
        "id": None,
        "user": player_block("Delta"),
        "series_winrate": 50.0,
        "games_winrate": 50.0,
        "avg_series_per_season": 1.0,
    },
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
            for number, name in enumerate(PLAYERS)
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


def test_the_derived_list_answers_every_field(
    client: Client, league: dict[str, int]
) -> None:
    """The full list, field for field, and the total the header carries."""
    resp = client.get("/stats/career")
    assert resp.status_code == 200
    assert resp.headers["X-Total-Count"] == "5"
    assert resp.json() == EXPECTED

    ratings = [row["rating"] for row in resp.json()]
    assert len(set(ratings)) == len(ratings), "the order must not rest on a tie"


def test_the_derived_page_answers_its_slice(
    client: Client, league: dict[str, int]
) -> None:
    """One page of two rows walks the same order as the full list."""
    resp = client.get("/stats/career?limit=2&offset=2")
    assert resp.status_code == 200
    assert resp.headers["X-Total-Count"] == "5"
    assert resp.json() == EXPECTED[2:4]


def test_the_search_keeps_the_rows_that_hold_it(
    client: Client, league: dict[str, int]
) -> None:
    """Four of the five names hold an "a", and the header counts those four."""
    resp = client.get("/stats/career?search=a")
    assert resp.status_code == 200
    assert resp.headers["X-Total-Count"] == "4"
    assert resp.json() == [EXPECTED[0], EXPECTED[2], EXPECTED[3], EXPECTED[4]]


def test_the_search_matches_without_case(
    client: Client, league: dict[str, int]
) -> None:
    """Three spellings of one name answer the same single row."""
    bodies = [
        client.get(f"/stats/career?search={term}").json()
        for term in ("alpha", "ALPHA", "AlPh")
    ]
    assert bodies == [[EXPECTED[0]]] * 3


def test_the_search_finds_a_player_who_holds_no_stored_row(
    client: Client, league: dict[str, int]
) -> None:
    """Charlie stands in the list from his series alone, and the search finds
    him."""
    resp = client.get("/stats/career?search=charl")
    assert resp.status_code == 200
    assert resp.headers["X-Total-Count"] == "1"
    assert resp.json() == [EXPECTED[3]]
    assert resp.json()[0]["id"] is None


def test_the_search_matches_the_user_name_of_a_stored_row(
    client: Client, league: dict[str, int]
) -> None:
    """A row whose player name is an old alias answers to the user name."""
    with Session() as session:
        player = User(
            name="Foxtrot",
            battleTag="Foxtrot#1000",
            discordTag="foxtrot",
            discordId="5",
            race=Race.HU,
            mmr=1500,
        )
        session.add(player)
        session.flush()
        session.add(PlayerCareerStats(user_id=player.id, player_name="Old Fox"))
        session.commit()

    resp = client.get("/stats/career?search=foxtrot")
    assert resp.status_code == 200
    assert resp.headers["X-Total-Count"] == "1"
    rows = resp.json()
    assert len(rows) == 1
    assert rows[0]["player_name"] == "Old Fox"
    assert rows[0]["user"]["name"] == "Foxtrot"


def test_the_search_pages_the_rows_it_keeps(
    client: Client, league: dict[str, int]
) -> None:
    """One row of the four kept, and the header still counts the four."""
    resp = client.get("/stats/career?search=a&limit=1&offset=1")
    assert resp.status_code == 200
    assert resp.headers["X-Total-Count"] == "4"
    assert resp.json() == [EXPECTED[2]]


def test_the_search_that_matches_nothing_answers_an_empty_list(
    client: Client, league: dict[str, int]
) -> None:
    resp = client.get("/stats/career?search=zulu")
    assert resp.status_code == 200
    assert resp.headers["X-Total-Count"] == "0"
    assert resp.json() == []


def test_an_empty_search_answers_the_whole_list(
    client: Client, league: dict[str, int]
) -> None:
    """The empty parameter answers the same bytes as no parameter at all."""
    plain = client.get("/stats/career")
    empty = client.get("/stats/career?search=")
    assert empty.content == plain.content
    assert empty.headers["X-Total-Count"] == plain.headers["X-Total-Count"] == "5"


def test_the_derived_player_answers_the_same_row(
    client: Client, league: dict[str, int]
) -> None:
    """One player, read by his user id, matches his row in the list."""
    resp = client.get(f"/stats/career/{league['Alpha']}")
    assert resp.status_code == 200
    assert resp.json() == EXPECTED[0]


def test_the_field_order_is_unchanged(client: Client, league: dict[str, int]) -> None:
    """The response keys, in order, so a model edit cannot reshuffle them."""
    rows = client.get("/stats/career").json()
    assert list(rows[0]) == list(EXPECTED[0])


def test_the_row_player_carries_no_collection(
    client: Client, league: dict[str, int]
) -> None:
    """The exact key set of the user object, so no collection returns unseen."""
    rows = client.get("/stats/career").json()
    for row in rows:
        if row["user"] is None:
            continue
        assert set(row["user"]) == {
            "id",
            "name",
            "battleTag",
            "discordTag",
            "discordId",
            "race",
            "mmr",
            "country",
            "fantasy_tier",
            "w3c_synced_at",
            "ladder_synced_at",
        }


def test_the_recalculate_route_is_gone(
    client: Client, auth_headers: dict[str, str], league: dict[str, int]
) -> None:
    """No write refreshes the career totals, because the reads compute them."""
    resp = client.post("/stats/career/recalculate", headers=auth_headers)
    # 405, not 404: the path still matches /stats/career/{stat_id}, which has
    # no POST
    assert resp.status_code == 405
    assert (
        "/stats/career/recalculate" not in client.get("/openapi.json").json()["paths"]
    )


def test_a_write_that_still_sends_the_totals_is_accepted(
    client: Client, auth_headers: dict[str, str], league: dict[str, int]
) -> None:
    """An old client sends the dropped fields, and the answer ignores them."""
    resp = client.put(
        "/stats/career/1",
        json={
            "historical_rating": 600,
            "rating": 9999,
            "series_won": 99,
            "series_lost": 99,
            "games_won": 99,
            "games_lost": 99,
            "seasons_played": 99,
            "series_winrate": 99.0,
            "games_winrate": 99.0,
            "avg_series_per_season": 99.0,
        },
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["historical_rating"] == 600
    assert body["series_won"] == 12
    assert body["rating"] != 9999


def test_the_unmapped_historical_row_takes_the_series_of_its_name(
    client: Client, league: dict[str, int]
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
