"""One player's ladder over the current w3champions season, on one race.

A cup's run page reads it beside a player's name: the record, the MMR span, the
last games and the record against each race. It reads the matches the app holds,
inside the w3champions season the app rates against and on one race alone.
"""

from datetime import UTC, datetime, timedelta

from httpx2 import Client

from app.core.db import Session
from app.models.enums import Race
from app.models.settings import Settings
from app.services.w3c_stats import W3C_SEASON_KEY
from tests.test_event_divisions import add_player
from tests.test_ladder_read import add_match
from tests.test_query_budget import count_statements

CURRENT = 25
FIRST = datetime(2026, 3, 2, 18, 0, tzinfo=UTC)


def rate_against(season: int) -> None:
    with Session.begin() as session:
        session.add(Settings(key=W3C_SEASON_KEY, value=str(season)))


def at(minutes: int) -> datetime:
    return FIRST + timedelta(minutes=minutes)


def test_a_player_reads_the_current_season_on_his_race(client: Client) -> None:
    rate_against(CURRENT)
    player = add_player("W3cSeasonA", {Race.HU: 1500})
    add_match(
        player,
        "a1",
        at(0),
        CURRENT,
        won=True,
        opp_race=Race.OC,
        mmr_before=1500,
        mmr_after=1512,
    )
    add_match(
        player,
        "a2",
        at(20),
        CURRENT,
        won=False,
        opp_race=Race.UD,
        mmr_before=1512,
        mmr_after=1500,
    )
    add_match(
        player,
        "a3",
        at(40),
        CURRENT,
        won=True,
        opp_race=Race.NE,
        mmr_before=1500,
        mmr_after=1530,
    )
    # too short to count as a game, though it still moves the MMR
    add_match(
        player,
        "a4",
        at(60),
        CURRENT,
        duration_s=60,
        won=False,
        opp_race=Race.HU,
        mmr_before=1530,
        mmr_after=1520,
    )
    # another season, and another race, stay out
    add_match(
        player, "b1", at(-600), CURRENT - 1, won=True, mmr_before=1400, mmr_after=1600
    )
    add_match(
        player,
        "c1",
        at(80),
        CURRENT,
        race=Race.OC,
        won=True,
        mmr_before=1200,
        mmr_after=1210,
    )

    body = client.get(f"/users/{player}/ladder/w3c-season").json()

    assert (body["race"], body["wc3_season"]) == ("HU", CURRENT)
    assert (body["games"], body["wins"], body["losses"]) == (3, 2, 1)
    assert body["form"] == "WLW"
    assert body["mmr"] == {"start": 1500, "min": 1500, "max": 1530, "current": 1520}
    assert body["vs_race"] == {
        "RANDOM": [0, 0],
        "HU": [0, 0],
        "OC": [1, 0],
        "NE": [1, 0],
        "UD": [0, 1],
    }


def test_the_race_named_is_the_one_read(client: Client) -> None:
    rate_against(CURRENT)
    player = add_player("W3cSeasonB", {Race.HU: 1500})
    add_match(player, "d1", at(0), CURRENT, won=True)
    add_match(
        player,
        "d2",
        at(20),
        CURRENT,
        race=Race.OC,
        won=False,
        mmr_before=1200,
        mmr_after=1190,
    )

    body = client.get(f"/users/{player}/ladder/w3c-season?race=OC").json()

    assert (body["race"], body["games"], body["losses"], body["form"]) == (
        "OC",
        1,
        1,
        "L",
    )
    assert body["mmr"]["current"] == 1190


def test_a_player_with_no_matches_reads_zeros(client: Client) -> None:
    rate_against(CURRENT)
    player = add_player("W3cSeasonC", {Race.HU: 1500})

    body = client.get(f"/users/{player}/ladder/w3c-season").json()

    assert (body["games"], body["wins"], body["losses"], body["form"]) == (0, 0, 0, "")
    assert body["mmr"] == {"start": None, "min": None, "max": None, "current": None}
    assert body["vs_race"] == {race.value: [0, 0] for race in Race}


def test_an_unknown_player_is_not_found(client: Client) -> None:
    assert client.get("/users/987654/ladder/w3c-season").status_code == 404


def test_the_read_costs_six_statements(client: Client) -> None:
    rate_against(CURRENT)
    player = add_player("W3cSeasonD", {Race.HU: 1500})
    add_match(player, "e1", at(0), CURRENT)

    with count_statements() as tally:
        assert client.get(f"/users/{player}/ladder/w3c-season").status_code == 200

    assert tally[0] == 6
