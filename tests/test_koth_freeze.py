"""A KOTH bracket is frozen once a row is cut into it.

Each test pins one rule of the cut: a signup, a result or a second race moves
no placed row; a row with no bracket is cut when its rating arrives; a bounds
save cuts by the rating stored at the cut, leaves both sides of a series on
the table where they stand, and cuts the rows that left; a row placed before
the stored rating existed keeps its bracket until a bounds save.
"""

from typing import Any

import pytest
from httpx2 import Client
from sqlmodel import col, select

from app.core.db import Session
from app.models.base import ident
from app.models.enums import Race
from app.models.event_entrant import EventEntrant
from app.models.user import User
from app.models.w3c_stats import W3CStats
from tests.test_koth import silent_w3c
from tests.test_koth_live import (
    board,
    bracket_ids,
    chat,
    crowned,
    only,
    play,
    set_bounds,
    start,
)
from tests.test_koth_moves import line, user_of
from tests.test_koth_night import entrants, open_night, rate, sign_up


def rerate(tag: str, mmr: int, race: Race = Race.HU) -> None:
    """Change the W3Champions rating the app holds for one race of a player."""
    with Session.begin() as session:
        user = session.scalars(select(User).where(col(User.battleTag) == tag)).one()
        for stats in session.scalars(
            select(W3CStats).where(
                col(W3CStats.user_id) == ident(user), col(W3CStats.race) == race
            )
        ):
            stats.mmr = mmr


def forget_cut(entrant_id: int) -> None:
    """Write the row as one placed before a cut stored the rating it used."""
    with Session.begin() as session:
        row = session.get(EventEntrant, entrant_id)
        assert row is not None
        row.mmr_at_seed = None


def row_of(client: Client, night: dict[str, Any], entrant_id: int) -> dict[str, Any]:
    return next(row for row in entrants(client, night["id"]) if row["id"] == entrant_id)


def open_series(
    client: Client,
    headers: dict[str, str],
    night: dict[str, Any],
    first: int,
    second: int,
) -> int:
    opened = start(client, headers, night["id"], first, second)
    assert opened.status_code == 201, opened.text
    division_id = row_of(client, night, first)["division_id"]
    return int(only(opened.json(), division_id)["open_series"]["series_id"])


def result(
    client: Client, headers: dict[str, str], night: dict[str, Any], series_id: int
) -> dict[str, Any]:
    """Side 1 wins the series."""
    done = client.put(
        f"/koth/nights/{night['id']}/series/{series_id}/result",
        json={"winner": 1},
        headers=headers,
    )
    assert done.status_code == 200, done.text
    return done.json()


def test_a_signup_leaves_a_king_whose_rating_rose_where_he_stands(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    """A rating that crossed a bound after the cut moves nobody on a signup."""
    night = open_night(client, auth_headers)
    _, _, low = bracket_ids(night)
    king = chat(client, night, "King#1001", 1400)
    rival = chat(client, night, "Rival#1002", 1400)
    play(client, auth_headers, night["id"], king, rival)
    before = row_of(client, night, king)
    rerate("King#1001", 1500)

    chat(client, night, "Late#1003", 1300)

    after = row_of(client, night, king)
    assert (after["division_id"], after["seed"]) == (low, before["seed"])
    assert crowned(board(client, night["id"]), low) == king


def test_a_result_leaves_a_side_whose_rating_rose_during_the_series(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    """The winner stays in his bracket and wears its crown, whatever his rating now."""
    night = open_night(client, auth_headers)
    _, _, low = bracket_ids(night)
    winner = chat(client, night, "Win#1001", 1400)
    loser = chat(client, night, "Lose#1002", 1400)
    series_id = open_series(client, auth_headers, night, winner, loser)
    rerate("Win#1001", 1500)

    payload = result(client, auth_headers, night, series_id)

    assert row_of(client, night, winner)["division_id"] == low
    assert crowned(payload, low) == winner


def test_a_second_race_moves_no_row_of_the_first(
    client: Client,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    seeded: dict[str, Any],
) -> None:
    """A player who enters again on another race leaves his first row where it stands."""
    silent_w3c(monkeypatch)
    night = open_night(client, auth_headers)
    _, _, low = bracket_ids(night)
    first = chat(client, night, "Two#1001", 1400)
    rerate("Two#1001", 1500)
    rate("Two#1001", 1300, Race.OC)

    assert sign_up(client, "Two#1001", "two", "orc").status_code == 200

    rows = {
        row["race"]: row
        for row in entrants(client, night["id"])
        if row["user"]["battleTag"] == "Two#1001"
    }
    assert (rows["HU"]["id"], rows["HU"]["division_id"]) == (first, low)
    assert rows["OC"]["division_id"] == low


def test_a_rating_that_arrives_cuts_the_row_last_and_stores_that_rating(
    client: Client,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    seeded: dict[str, Any],
) -> None:
    """A row with no bracket is cut at the next signup; the cut keeps the rating it used."""
    silent_w3c(monkeypatch)
    night = open_night(client, auth_headers)
    _, middle, _ = bracket_ids(night)
    seated = chat(client, night, "Seat#1001", 1500)
    assert sign_up(client, "Ghost#9999", "ghost", "human").status_code == 200
    ghost = next(
        row["id"]
        for row in entrants(client, night["id"])
        if row["user"]["battleTag"] == "Ghost#9999"
    )
    assert row_of(client, night, ghost)["division_id"] is None
    rate("Ghost#9999", 1500)

    chat(client, night, "Next#1003", 1200)

    row = row_of(client, night, ghost)
    assert (row["division_id"], row["mmr_at_seed"]) == (middle, 1500)
    assert line(board(client, night["id"]), middle) == [[seated], [ghost]]


@pytest.mark.parametrize(
    ("today", "bounds", "moves"),
    [
        (1400, [1600, 1350, 0], True),
        (1300, [1600, 1350, 0], True),
        (1400, [1600, 1420, 0], False),
    ],
    ids=["bound-falls-below", "rating-fell-since", "bound-stays-above"],
)
def test_a_bounds_save_cuts_by_the_rating_the_row_was_cut_with(
    client: Client,
    auth_headers: dict[str, str],
    seeded: dict[str, Any],
    today: int,
    bounds: list[int],
    moves: bool,
) -> None:
    """A row cut at 1400 moves only when a bound crosses 1400, whatever it rates today."""
    night = open_night(client, auth_headers)
    _, middle, low = bracket_ids(night)
    standing = chat(client, night, "Mid#1001", 1500)
    cut = chat(client, night, "Cut#1002", 1400)
    rerate("Cut#1002", today)

    resp = set_bounds(client, auth_headers, night, bounds)

    assert resp.status_code == 200, resp.text
    payload = resp.json()
    expected = ([[standing], [cut]], []) if moves else ([[standing]], [[cut]])
    assert (line(payload, middle), line(payload, low)) == expected


def king_at_the_table(
    client: Client, headers: dict[str, str], night: dict[str, Any]
) -> tuple[int, int, int, int]:
    """A king of the weakest bracket in a series, and the row he beat, all cut at 1400."""
    king = chat(client, night, "King#2001", 1400)
    beaten = chat(client, night, "Beat#2002", 1400)
    play(client, headers, night["id"], king, beaten)
    challenger = chat(client, night, "Chal#2003", 1400)
    return (
        king,
        beaten,
        challenger,
        open_series(client, headers, night, king, challenger),
    )


def test_both_sides_at_the_table_keep_their_bracket_and_the_crown_through_a_bounds_save(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    """The save moves the row that is free; the king and his challenger stay, also after the win."""
    night = open_night(client, auth_headers)
    _, middle, low = bracket_ids(night)
    king, beaten, challenger, series_id = king_at_the_table(client, auth_headers, night)

    saved = set_bounds(client, auth_headers, night, [1600, 1350, 0])

    assert saved.status_code == 200, saved.text
    assert line(saved.json(), middle) == [[beaten]]
    assert crowned(saved.json(), low) == king
    assert only(saved.json(), low)["open_series"]["series_id"] == series_id

    payload = result(client, auth_headers, night, series_id)

    assert crowned(payload, low) == king
    assert line(payload, low) == [[challenger]]
    assert line(payload, middle) == [[beaten]]


def test_a_bounds_save_after_the_series_moves_both_sides(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    """Saving the bounds again once the table is clear cuts the two rows it held."""
    night = open_night(client, auth_headers)
    _, middle, low = bracket_ids(night)
    king, beaten, challenger, series_id = king_at_the_table(client, auth_headers, night)
    assert set_bounds(client, auth_headers, night, [1600, 1350, 0]).status_code == 200
    result(client, auth_headers, night, series_id)

    saved = set_bounds(client, auth_headers, night, [1600, 1350, 0])

    assert saved.status_code == 200, saved.text
    payload = saved.json()
    assert crowned(payload, low) is None
    assert crowned(payload, middle) is None
    assert line(payload, low) == []
    assert line(payload, middle) == [[beaten], [king], [challenger]]


@pytest.mark.parametrize("way", ["restore", "chat", "admin"])
def test_a_row_that_left_is_cut_by_the_bounds_and_comes_back_last_there(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any], way: str
) -> None:
    """A bounds save cuts a row that left, so it returns to the end of its new line."""
    night = open_night(client, auth_headers)
    _, middle, _ = bracket_ids(night)
    standing = chat(client, night, "Mid#3001", 1500)
    gone = chat(client, night, "Gone#3002", 1400)
    removed = client.delete(
        f"/koth/nights/{night['id']}/entrants/{gone}", headers=auth_headers
    )
    assert removed.status_code == 200, removed.text

    assert set_bounds(client, auth_headers, night, [1600, 1350, 0]).status_code == 200
    assert row_of(client, night, gone)["division_id"] == middle
    later = chat(client, night, "Late#3003", 1500)

    if way == "restore":
        back = client.post(
            f"/koth/nights/{night['id']}/entrants/{gone}/restore", headers=auth_headers
        )
    elif way == "chat":
        back = sign_up(client, "Gone#3002", "gone", "human")
    else:
        back = client.post(
            f"/events/{night['id']}/entrants/admin",
            json={"user_id": user_of(client, night["id"], gone), "race": "HU"},
            headers=auth_headers,
        )
    assert back.status_code in (200, 201), back.text

    assert line(board(client, night["id"]), middle) == [[standing], [later], [gone]]
    seeds = [
        row["seed"]
        for row in entrants(client, night["id"])
        if row["division_id"] == middle and row["withdrawn_at"] is None
    ]
    assert len(seeds) == len(set(seeds)), seeds


def test_a_signup_leaves_a_row_with_no_stored_rating_and_stores_one(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    """A row placed before the cut stored its rating keeps its bracket on a signup."""
    night = open_night(client, auth_headers)
    _, _, low = bracket_ids(night)
    old = chat(client, night, "Old#4001", 1400)
    forget_cut(old)
    rerate("Old#4001", 1500)

    chat(client, night, "New#4002", 1300)

    row = row_of(client, night, old)
    assert (row["division_id"], row["mmr_at_seed"]) == (low, 1500)


def test_a_bounds_save_cuts_a_row_with_no_stored_rating_by_its_rating_today(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    """With no stored rating to read, the save reads the live one and stores it."""
    night = open_night(client, auth_headers)
    _, middle, _ = bracket_ids(night)
    old = chat(client, night, "Old#5001", 1400)
    forget_cut(old)
    rerate("Old#5001", 1500)

    assert set_bounds(client, auth_headers, night, [1600, 1450, 0]).status_code == 200

    row = row_of(client, night, old)
    assert (row["division_id"], row["mmr_at_seed"]) == (middle, 1500)
