"""One live MMR summary per player, and the windowed ladder reads.

`w3c_stats.summarize` reads a player's w3cstats rows against the live window,
the current W3C season and the one before it: per race the newest window row's
mmr and the window's games, and on a profile a race with no window row from its
newest older row, flagged stale. The main race is the window race with the top
mmr among those with 10 or more games. A list read loads the window rows only.
A roster of an event that is over carries the MMR each player entered it with.
"""

from typing import Any

import pytest
from httpx2 import Client

from app.core.db import Session
from app.models.enums import Race
from app.models.relationships import DBUserSeasonSignup
from app.models.w3c_stats import W3CStats, W3CStatsPublic
from app.services.events import race_ratings
from app.services.w3c_stats import summarize
from tests.test_series_row_mmr import (  # noqa: F401  # fixtures
    finished,
    play,
    signed_up,
)

CURRENT = 25

# Per seeded player index: (race, W3C season, mmr, games)
STATS = {
    0: [("HU", 25, 1800, 20), ("HU", 24, 1750, 15), ("NE", 23, 1600, 30)]
    + [("NE", 20, 1500, 40)],
    1: [("OC", 24, 1500, 6), ("UD", 25, 1650, 4), ("UD", 24, 1400, 8)],
    2: [("HU", 20, 1700, 50)],
    3: [],
}

# What the rules before the summary answered on STATS, captured on this fixture:
# events.race_ratings (newest of three seasons, "index:race" -> (season, mmr))
# and the dashboard helper (current, else previous, else newest of any age)
OLD_RATINGS = {"0:HU": (25, 1800), "0:NE": (23, 1600), "1:OC": (24, 1500)} | {
    "1:UD": (25, 1650)
}
DASHBOARD = OLD_RATINGS | {"2:HU": (20, 1700)}


def rows(*stats: tuple[str, int, int | None, int]) -> list[W3CStatsPublic]:
    return [
        W3CStatsPublic(
            id=number, user_id=1, race=race, wc3_season=season, mmr=mmr, games=games
        )
        for number, (race, season, mmr, games) in enumerate(stats)
    ]


def test_a_window_race_reads_its_newest_row_and_sums_the_window_games() -> None:
    races, main = summarize(rows(*STATS[0]), CURRENT)
    assert [(row.race, row.wc3_season, row.mmr, row.games) for row in races] == [
        ("HU", 25, 1800, 35)
    ]
    assert not races[0].stale
    assert main == "HU"


def test_stale_races_come_only_when_asked_and_after_the_window_races() -> None:
    races, _ = summarize(rows(*STATS[0]), CURRENT, stale=True)
    assert [(row.race, row.wc3_season, row.mmr, row.stale) for row in races] == [
        ("HU", 25, 1800, False),
        ("NE", 23, 1600, True),
    ]
    # the stale row's own games; the older NE row is not summed
    assert races[1].games == 30


def test_window_races_order_by_mmr_and_the_main_race_needs_ten_games() -> None:
    races, main = summarize(rows(*STATS[1]), CURRENT)
    assert [(row.race, row.mmr, row.games) for row in races] == [
        ("UD", 1650, 12),
        ("OC", 1500, 6),
    ]
    assert main == "UD"
    # the top race short of ten games is no main race
    races, main = summarize(rows(("NE", 25, 1900, 9), ("HU", 24, 1600, 10)), CURRENT)
    assert [row.race for row in races] == ["NE", "HU"]
    assert main == "HU"
    assert summarize(rows(("NE", 25, 1900, 9)), CURRENT)[1] is None


def test_a_window_race_reads_its_newest_rated_row() -> None:
    """An unrated newer row gives way to the newest rated one, as in
    race_ratings; with no rated row the newest window row answers."""
    races, _ = summarize(rows(("HU", 25, None, 5), ("HU", 24, 1750, 15)), CURRENT)
    assert [(row.wc3_season, row.mmr, row.games) for row in races] == [(24, 1750, 20)]
    races, _ = summarize(rows(("HU", 25, None, 5), ("HU", 24, None, 15)), CURRENT)
    assert [(row.wc3_season, row.mmr, row.games) for row in races] == [(25, None, 20)]


def test_stale_races_order_newest_first() -> None:
    races, main = summarize(
        rows(("HU", 20, 1700, 50), ("OC", 22, 1300, 5)), CURRENT, stale=True
    )
    assert [(row.race, row.wc3_season) for row in races] == [("OC", 22), ("HU", 20)]
    assert main is None


def test_a_player_with_no_rows_has_no_summary() -> None:
    assert summarize([], CURRENT) == ([], None)
    assert summarize([], CURRENT, stale=True) == ([], None)
    assert summarize(rows(("HU", 20, 1700, 50)), CURRENT) == ([], None)


@pytest.fixture
def stats(seeded: dict[str, Any]) -> list[int]:
    """STATS stored for the four seeded players; the newest season is CURRENT."""
    ids = seeded["player_ids"]
    with Session() as session:
        for index, stored in STATS.items():
            for race, season, mmr, games in stored:
                session.add(
                    W3CStats(
                        user_id=ids[index],
                        race=Race(race),
                        wc3_season=season,
                        mmr=mmr,
                        games=games,
                        wins=games // 2,
                        losses=games - games // 2,
                    )
                )
        session.commit()
    return ids


def by_key(ids: list[int], races: dict[int, list[dict[str, Any]]]) -> dict[str, Any]:
    return {
        f"{ids.index(user_id)}:{row['race']}": (row["wc3_season"], row["mmr"])
        for user_id, rows_of in races.items()
        for row in rows_of
    }


def test_the_profile_agrees_with_the_old_picks(
    client: Client, stats: list[int]
) -> None:
    """Every old pick inside the window is the summary's. Outside it, the old
    rating of 0:NE (season 23) leaves the live figures by design and shows on
    the profile as stale, where the dashboard helper showed it too."""
    profiles = {
        user_id: client.get(f"/users/{user_id}").json()["race_mmrs"]
        for user_id in stats
    }
    summary = by_key(stats, profiles)
    for key, (season, mmr) in OLD_RATINGS.items():
        if season >= CURRENT - 1:
            assert summary[key] == (season, mmr)
    assert summary == DASHBOARD
    stale = {
        key
        for user_id, rows_of in profiles.items()
        for key, row in (
            (f"{stats.index(user_id)}:{row['race']}", row) for row in rows_of
        )
        if row["stale"]
    }
    assert stale == {"0:NE", "2:HU"}


def test_list_reads_carry_the_window_alone(client: Client, stats: list[int]) -> None:
    users = client.get("/users").json()
    listed = {user["id"]: user for user in users if user["id"] in stats}
    assert all("w3c_stats" not in user for user in users)
    summary = by_key(stats, {i: u["race_mmrs"] for i, u in listed.items()})
    assert summary == {
        key: pick for key, pick in OLD_RATINGS.items() if pick[0] >= CURRENT - 1
    }
    assert [listed[user_id]["main_race"] for user_id in stats] == [
        "HU",
        "UD",
        None,
        None,
    ]


def test_the_signups_list_carries_the_window_alone(
    client: Client, stats: list[int], seeded: dict[str, Any]
) -> None:
    with Session() as session:
        for user_id in stats:
            session.add(
                DBUserSeasonSignup(
                    user_id=user_id, season_id=seeded["season_id"], race=Race.HU
                )
            )
        session.commit()
    signed = client.get(f"/events/{seeded['season_id']}/signups").json()
    assert all("w3c_stats" not in user for user in signed)
    summary = by_key(stats, {user["id"]: user["race_mmrs"] for user in signed})
    assert summary == {
        key: pick for key, pick in OLD_RATINGS.items() if pick[0] >= CURRENT - 1
    }


def test_ratings_read_the_window(stats: list[int]) -> None:
    """race_ratings answers the old pick inside the window and drops 0:NE."""
    pairs = [(user_id, race) for user_id in stats for race in ("HU", "NE", "OC", "UD")]
    with Session() as session:
        rated = race_ratings(session, pairs)
    assert {
        f"{stats.index(user_id)}:{race}": mmr for (user_id, race), mmr in rated.items()
    } == {
        key: mmr for key, (season, mmr) in OLD_RATINGS.items() if season >= CURRENT - 1
    }


def test_a_finished_roster_carries_the_mmr_entered_with(
    client: Client,
    finished: dict[str, Any],  # noqa: F811
) -> None:
    """The ladder rule at the season's first day (2026-01-05) on the signup
    race, inside the event's W3C seasons: P1 (HU) played on both sides of it
    and takes the match after, P3 (NE) only before it and keeps what it left
    him with, P2 (OC) only in a season outside the event and has none."""
    p1, p2, p3, _ = finished["player_ids"]
    # the series time is 2026-01-07 19:00 UTC; -60 hours is 2026-01-05 07:00
    play(p1, Race.HU, -70, 25, (1400, 1410))
    play(p1, Race.HU, -60, 25, (1420, 1440))
    play(p3, Race.NE, -72, 25, (1500, 1505))
    play(p2, Race.OC, -80, 20, (1600, 1610))
    teams = client.get(f"/events/{finished['season_id']}/teams").json()
    entered = {
        player["id"]: player["mmr_entered"]
        for team in teams
        for players in team["player_by_season"].values()
        for player in players
    }
    assert entered == {p1: 1420, p2: None, p3: 1505, finished["player_ids"][3]: None}


def test_a_running_roster_carries_no_mmr_entered(
    client: Client,
    signed_up: dict[str, Any],  # noqa: F811
) -> None:
    """A running event reads the live window; nobody has an entered figure."""
    p1 = signed_up["player_ids"][0]
    play(p1, Race.HU, -60, 25, (1420, 1440))
    teams = client.get(f"/events/{signed_up['season_id']}/teams").json()
    entered = [
        player["mmr_entered"]
        for team in teams
        for players in team["player_by_season"].values()
        for player in players
    ]
    assert entered
    assert set(entered) == {None}
