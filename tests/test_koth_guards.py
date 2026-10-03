"""Guards of a KOTH night: one table per player, a closed night stays as it is.

Each test pins one rule: a player in a running series starts no second one in
another bracket; a closed night is never cut again; the close pays the king
and the players who played, and nobody else.
"""

from typing import Any

import pytest
from httpx2 import Client
from sqlmodel import col, select

from app.core.db import Session
from app.models.w3c_stats import W3CStats
from tests.test_awards import awarded
from tests.test_koth_live import (
    _open_id,
    bracket_ids,
    chat,
    place,
    place_user,
    play,
    start,
)
from tests.test_koth_moves import move, stored_king, two_races, user_of
from tests.test_koth_night import enrol, entrants, open_night

# Every signup asks W3Champions, so each test here answers for it
pytestmark = pytest.mark.usefixtures("quiet_w3c")


def test_a_player_in_a_running_series_starts_none_in_another_bracket(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    """His row in Bracket 2 waits until his series in Bracket 1 has a result."""
    night = open_night(client, auth_headers)
    _, middle, low = bracket_ids(night)
    duo = two_races("Duo#1", 1500)
    duo_low = place_user(client, auth_headers, night, duo, low, "HU")
    duo_middle = place_user(client, auth_headers, night, duo, middle, "NE")
    foe_low = place(client, auth_headers, night, "Foe#2", 1200, low)
    foe_middle = place(client, auth_headers, night, "Mid#3", 1500, middle)
    opened = start(client, auth_headers, night["id"], duo_low, foe_low)
    assert opened.status_code == 201, opened.text

    for first, second in ((duo_middle, foe_middle), (foe_middle, duo_middle)):
        refused = start(client, auth_headers, night["id"], first, second)
        assert refused.status_code == 409, refused.text
        assert refused.json()["error"] == "Duo is playing in another bracket"

    series_id = _open_id(opened.json(), duo_low)
    done = client.put(
        f"/koth/nights/{night['id']}/series/{series_id}/result",
        json={"winner": 1},
        headers=auth_headers,
    )
    assert done.status_code == 200, done.text
    again = start(client, auth_headers, night["id"], duo_middle, foe_middle)
    assert again.status_code == 201, again.text


def test_an_admin_add_cuts_no_row_of_a_closed_night(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    """A rating that falls after the close moves no row and takes no crown."""
    night = open_night(client, auth_headers)
    _, middle, _ = bracket_ids(night)
    king = chat(client, night, "Hold#1111", 1500)
    rival = chat(client, night, "Hold#2222", 1500)
    play(client, auth_headers, night["id"], king, rival)
    assert stored_king(middle) == king
    closed = client.post(f"/koth/nights/{night['id']}/close", headers=auth_headers)
    assert closed.status_code == 200, closed.text
    # A cut by this rating would drop the king to the lowest bracket
    with Session.begin() as session:
        stats = session.scalars(
            select(W3CStats).where(
                col(W3CStats.user_id) == user_of(client, night["id"], king)
            )
        ).one()
        stats.mmr = 1200

    added = client.post(
        f"/events/{night['id']}/entrants/admin",
        json={"user_id": enrol("Late#3333", 1500), "race": "HU"},
        headers=auth_headers,
    )

    assert added.status_code == 201, added.text
    held = {row["id"]: row["division_id"] for row in entrants(client, night["id"])}
    assert held[king] == middle
    assert held[added.json()["id"]] is None
    assert stored_king(middle) == king


def crown(
    client: Client,
    headers: dict[str, str],
    night_id: int,
    division_id: int,
    entrant_id: int | None,
) -> None:
    """Pass the crown of a bracket by hand, or empty its throne."""
    resp = client.put(
        f"/koth/nights/{night_id}/brackets/{division_id}/crown",
        json={"entrant_id": entrant_id},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text


def close(client: Client, headers: dict[str, str], night_id: int) -> None:
    resp = client.post(f"/koth/nights/{night_id}/close", headers=headers)
    assert resp.status_code == 200, resp.text


def test_a_bracket_that_played_nothing_pays_nobody(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    """Two players stand in line and nobody plays: the close pays no award."""
    night = open_night(client, auth_headers)
    top = bracket_ids(night)[0]
    place(client, auth_headers, night, "Wait#1", 1700, top)
    place(client, auth_headers, night, "Wait#2", 1700, top)

    close(client, auth_headers, night["id"])

    assert awarded(night["id"]) == []


def test_a_king_who_stepped_down_leaves_no_champion(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    """The two who played take places 2 and 3; place 1 stays empty."""
    night = open_night(client, auth_headers)
    top = bracket_ids(night)[0]
    first = place(client, auth_headers, night, "Step#1", 1700, top)
    second = place(client, auth_headers, night, "Step#2", 1700, top)
    play(client, auth_headers, night["id"], first, second)
    crown(client, auth_headers, night["id"], top, None)

    close(client, auth_headers, night["id"])

    assert awarded(night["id"]) == [
        (user_of(client, night["id"], first), 2, "Runner-up"),
        (user_of(client, night["id"], second), 3, "Third"),
    ]


def test_a_player_who_only_signed_up_takes_no_place(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    night = open_night(client, auth_headers)
    top = bracket_ids(night)[0]
    king = place(client, auth_headers, night, "Reign#1", 1700, top)
    rival = place(client, auth_headers, night, "Reign#2", 1700, top)
    place(client, auth_headers, night, "Reign#3", 1700, top)
    play(client, auth_headers, night["id"], king, rival)

    close(client, auth_headers, night["id"])

    assert awarded(night["id"]) == [
        (user_of(client, night["id"], king), 1, "Champion"),
        (user_of(client, night["id"], rival), 2, "Runner-up"),
    ]


def test_a_king_crowned_by_hand_who_played_nothing_is_champion(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    night = open_night(client, auth_headers)
    top = bracket_ids(night)[0]
    first = place(client, auth_headers, night, "Hand#1", 1700, top)
    second = place(client, auth_headers, night, "Hand#2", 1700, top)
    heir = place(client, auth_headers, night, "Hand#3", 1700, top)
    play(client, auth_headers, night["id"], first, second)
    crown(client, auth_headers, night["id"], top, heir)

    close(client, auth_headers, night["id"])

    assert awarded(night["id"]) == [
        (user_of(client, night["id"], heir), 1, "Champion"),
        (user_of(client, night["id"], first), 2, "Runner-up"),
        (user_of(client, night["id"], second), 3, "Third"),
    ]


def test_a_win_over_a_row_that_moved_away_still_counts_as_played(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    """The beaten row now stands in another bracket; the winner keeps a place."""
    night = open_night(client, auth_headers)
    top, middle, _ = bracket_ids(night)
    winner = place(client, auth_headers, night, "Beat#1", 1700, top)
    beaten = place(client, auth_headers, night, "Beat#2", 1700, top)
    heir = place(client, auth_headers, night, "Beat#3", 1700, top)
    play(client, auth_headers, night["id"], winner, beaten)
    crown(client, auth_headers, night["id"], top, heir)
    moved = move(client, auth_headers, night["id"], beaten, middle)
    assert moved.status_code == 200, moved.text

    close(client, auth_headers, night["id"])

    assert awarded(night["id"]) == [
        (user_of(client, night["id"], heir), 1, "Champion"),
        (user_of(client, night["id"], winner), 2, "Runner-up"),
    ]
