"""The reduced series lists carry the W3C rating of both sides.

`SeriesPublic.from_series_reduced` leaves `w3c_stats` empty, so the season
list (the upcoming page) and `GET /player-series` (the round cards of the
player page) hold the rating on the row itself. The rule is the one the
stage rows and the entrant lists use: the newest stored W3C season that
carries a rating above 0 on the race the row names, three seasons back and
no further, null otherwise.
"""

from typing import Any

import pytest
from httpx2 import Client

from app.core.db import Session
from app.models.base import ident
from app.models.enums import Race
from app.models.relationships import DBUserSeasonSignup
from app.models.series import Series
from app.models.user import User
from app.models.w3c_stats import W3CStats
from tests.test_player_session import member_session
from tests.test_query_budget import count_statements

# The race each seeded player signs up on, in player_ids order
SIGNUP_RACES = [Race.HU, Race.OC, Race.NE, Race.UD]


@pytest.fixture
def signed_up(seeded: dict[str, Any]) -> dict[str, Any]:
    """The seeded league with one season signup per player, so a row names a race."""
    with Session() as session:
        for user_id, race in zip(seeded["player_ids"], SIGNUP_RACES, strict=True):
            session.add(
                DBUserSeasonSignup(
                    user_id=user_id, season_id=seeded["season_id"], race=race
                )
            )
        session.commit()
    return seeded


def rate(*rows: tuple[int, Race, int, int | None]) -> None:
    """Store one W3C stats row per (player, race, season, rating) named."""
    with Session() as session:
        session.add_all(
            W3CStats(user_id=user_id, race=race, wc3_season=season, mmr=mmr)
            for user_id, race, season, mmr in rows
        )
        session.commit()


def season_rows(client: Client, season_id: int) -> list[dict[str, Any]]:
    """The season series list the upcoming page reads."""
    resp = client.post(f"/events/{season_id}/series/search?query=id > 0")
    assert resp.status_code == 200, resp.text
    return resp.json()


def played(rows: list[dict[str, Any]], series_id: int) -> dict[str, Any]:
    return next(row for row in rows if row["id"] == series_id)


def test_the_season_list_rates_both_sides_on_the_race_the_row_names(
    client: Client, signed_up: dict[str, Any]
) -> None:
    """The reduced player carries no stats, so the row holds the rating itself."""
    first, _, third, _ = signed_up["player_ids"]
    rate(
        (first, Race.HU, 20, 1500),
        # A rating on another race is not the one the row names
        (first, Race.OC, 20, 900),
        (third, Race.NE, 20, 1400),
    )

    row = played(
        season_rows(client, signed_up["season_id"]), signed_up["series_played_id"]
    )

    assert (row["player1_race"], row["player2_race"]) == ("HU", "NE")
    assert (row["player1_mmr"], row["player2_mmr"]) == (1500, 1400)
    assert row["player1"]["w3c_stats"] == []


def test_the_player_series_read_rates_both_sides(
    client: Client, signed_up: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    """The round cards of the player page read the same two fields."""
    first, _, third, _ = signed_up["player_ids"]
    rate((first, Race.HU, 20, 1500), (third, Race.NE, 20, 1400))
    headers = member_session(monkeypatch)

    body = client.get("/player-series", headers=headers).json()

    row = played(body["series"], signed_up["series_played_id"])
    assert (row["player1_mmr"], row["player2_mmr"]) == (1500, 1400)
    assert row["player1"]["w3c_stats"] == []


def test_a_row_reads_the_newest_rated_season_of_the_race(
    client: Client, signed_up: dict[str, Any]
) -> None:
    """The newest stored season that carries a rating wins, and a season that
    carries none, null or zero, is walked back over."""
    first, _, third, _ = signed_up["player_ids"]
    rate(
        (first, Race.HU, 19, 1600),
        (first, Race.HU, 20, 1700),
        (third, Race.NE, 19, 1400),
        (third, Race.NE, 20, 0),
        (third, Race.NE, 21, None),
    )

    row = played(
        season_rows(client, signed_up["season_id"]), signed_up["series_played_id"]
    )

    assert (row["player1_mmr"], row["player2_mmr"]) == (1700, 1400)


def test_a_row_reads_no_rating_older_than_the_window(
    client: Client, signed_up: dict[str, Any]
) -> None:
    """The window hangs on the season the app is on, three seasons back."""
    first, _, third, _ = signed_up["player_ids"]
    rate((first, Race.HU, 15, 1900), (third, Race.NE, 23, 1500))

    row = played(
        season_rows(client, signed_up["season_id"]), signed_up["series_played_id"]
    )

    assert (row["player1_mmr"], row["player2_mmr"]) == (None, 1500)


def test_a_side_with_no_stats_on_its_race_is_rated_null(
    client: Client, signed_up: dict[str, Any]
) -> None:
    first, _, _, _ = signed_up["player_ids"]
    rate((first, Race.HU, 20, 1500))

    row = played(
        season_rows(client, signed_up["season_id"]), signed_up["series_played_id"]
    )

    assert (row["player1_mmr"], row["player2_mmr"]) == (1500, None)


def test_an_off_race_row_is_rated_on_the_race_it_played(
    client: Client, signed_up: dict[str, Any]
) -> None:
    """The row names the off race, so the rating follows the off race."""
    first, _, third, _ = signed_up["player_ids"]
    rate(
        (first, Race.HU, 20, 1500),
        (first, Race.OC, 20, 900),
        (third, Race.NE, 20, 1400),
    )
    with Session() as session:
        series = session.get(Series, signed_up["series_played_id"])
        assert series is not None
        series.player1_off_race = Race.OC
        session.commit()

    row = played(
        season_rows(client, signed_up["season_id"]), signed_up["series_played_id"]
    )

    assert row["player1_race"] == "OC"
    assert (row["player1_mmr"], row["player2_mmr"]) == (900, 1400)


def grow_series(seeded: dict[str, Any], count: int) -> None:
    """More series in the season, so a per-row rating read would be visible.

    Every series meets a new opponent, because one fixture holds one series
    per pair of players.
    """
    first = seeded["player_ids"][0]
    with Session() as session:
        for number in range(count):
            tag = f"G{number:02d}"
            opponent = User(
                name=tag,
                battleTag=f"{tag}#9999",
                discordTag=tag.lower(),
                discordId=f"9{number:02d}",
                race=Race.NE,
            )
            session.add(opponent)
            session.flush()
            session.add(
                DBUserSeasonSignup(
                    user_id=ident(opponent),
                    season_id=seeded["season_id"],
                    race=Race.NE,
                )
            )
            session.add(
                Series(
                    match_id=seeded["match_id"],
                    player1_id=first,
                    player2_id=ident(opponent),
                    host_player_id=first,
                )
            )
        session.commit()


def test_the_season_list_costs_a_constant_number_of_statements(
    client: Client, signed_up: dict[str, Any]
) -> None:
    """Ten times the series, the same number of statements: the rating of every
    row is read for the whole list at once."""
    first, _, third, _ = signed_up["player_ids"]
    rate((first, Race.HU, 20, 1500), (third, Race.NE, 20, 1400))
    season_id = signed_up["season_id"]

    with count_statements() as small:
        assert len(season_rows(client, season_id)) == 2
    grow_series(signed_up, 18)
    with count_statements() as large:
        rows = season_rows(client, season_id)

    assert len(rows) == 20
    # every row P1 plays, the seeded one and the eighteen grown ones
    assert sum(row["player1_mmr"] == 1500 for row in rows) == 19
    assert small[0] == large[0]
    # nine today; the guard is that it is a constant, not that it is low
    assert large[0] <= 10, large[0]


def test_the_player_series_read_costs_a_constant_number_of_statements(
    client: Client, signed_up: dict[str, Any], monkeypatch: pytest.MonkeyPatch
) -> None:
    first, _, third, _ = signed_up["player_ids"]
    rate((first, Race.HU, 20, 1500), (third, Race.NE, 20, 1400))
    headers = member_session(monkeypatch)

    # the first read of the session warms what the route caches per caller
    assert client.get("/player-series", headers=headers).status_code == 200
    with count_statements() as small:
        assert client.get("/player-series", headers=headers).status_code == 200
    grow_series(signed_up, 18)
    with count_statements() as large:
        body = client.get("/player-series", headers=headers).json()

    assert len(body["series"]) == 19
    assert all(row["player1_mmr"] == 1500 for row in body["series"])
    assert small[0] == large[0]
