"""The KOTH line and crown rules an admin meets while fixing a running night.

Each test pins one rule: a queue write reorders only the rows it names, a
result sent again keeps its kind, and a crowned race that leaves the table
passes the crown to another race of the player with no forfeit.
"""

from typing import Any

from httpx2 import Client

from tests.test_koth_live import (
    board,
    bracket_ids,
    crowned,
    flip,
    only,
    place,
    place_user,
    play,
    start,
)
from tests.test_koth_moves import line, two_races
from tests.test_koth_night import open_night


def set_queue(
    client: Client,
    headers: dict[str, str],
    night_id: int,
    division_id: int,
    ids: list[int],
) -> dict[str, Any]:
    resp = client.put(
        f"/koth/nights/{night_id}/brackets/{division_id}/queue",
        json={"entrant_ids": ids},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def set_crown(
    client: Client,
    headers: dict[str, str],
    night_id: int,
    division_id: int,
    entrant_id: int | None,
) -> dict[str, Any]:
    resp = client.put(
        f"/koth/nights/{night_id}/brackets/{division_id}/crown",
        json={"entrant_id": entrant_id},
        headers=headers,
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def leave(
    client: Client, headers: dict[str, str], night_id: int, entrant_id: int
) -> dict[str, Any]:
    resp = client.delete(
        f"/koth/nights/{night_id}/entrants/{entrant_id}", headers=headers
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def rows_of(payload: dict[str, Any], division_id: int) -> list[int]:
    """The line as the first race row of each seat, first in line first."""
    return [
        seat["rows"][0]["entrant_id"] for seat in only(payload, division_id)["queue"]
    ]


def test_a_queue_write_keeps_the_players_at_the_table_in_their_places(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    """A drag during a side game leaves its winner ahead of the rows behind him."""
    night = open_night(client, auth_headers)
    top = bracket_ids(night)[0]
    p = place(client, auth_headers, night, "P#1", 1700, top)
    q = place(client, auth_headers, night, "Q#2", 1700, top)
    r = place(client, auth_headers, night, "R#3", 1700, top)
    s = place(client, auth_headers, night, "S#4", 1700, top)
    t = place(client, auth_headers, night, "T#5", 1700, top)
    k = place(client, auth_headers, night, "K#6", 1700, top)
    play(client, auth_headers, night["id"], k, q)
    assert rows_of(board(client, night["id"]), top) == [p, r, s, t, q]
    opened = start(client, auth_headers, night["id"], p, r)
    assert opened.status_code == 201, opened.text

    dragged = set_queue(client, auth_headers, night["id"], top, [q, s, t])
    assert rows_of(dragged, top) == [q, s, t]
    series_id = only(dragged, top)["open_series"]["series_id"]
    done = flip(client, auth_headers, night["id"], series_id, 1)

    # P and R kept places 1 and 2; Q, S and T swapped among places 3, 4 and 6
    assert crowned(done, top) == k
    assert rows_of(done, top) == [p, q, s, t, r]


def test_a_queue_write_keeps_the_kings_place_for_when_he_steps_down(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    """The write never names the king, so he stands first again when he steps down."""
    night = open_night(client, auth_headers)
    top = bracket_ids(night)[0]
    k = place(client, auth_headers, night, "K#1", 1700, top)
    p = place(client, auth_headers, night, "P#2", 1700, top)
    q = place(client, auth_headers, night, "Q#3", 1700, top)
    r = place(client, auth_headers, night, "R#4", 1700, top)
    play(client, auth_headers, night["id"], k, p)
    assert rows_of(board(client, night["id"]), top) == [q, r, p]

    set_queue(client, auth_headers, night["id"], top, [r, q, p])
    payload = set_crown(client, auth_headers, night["id"], top, None)

    assert rows_of(payload, top) == [k, r, q, p]


def test_a_resent_forfeit_stays_a_forfeit_and_a_turned_one_reads_played(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    """The same winner sent again keeps the kind; another winner makes it played."""
    night = open_night(client, auth_headers)
    top = bracket_ids(night)[0]
    a = place(client, auth_headers, night, "A#1", 1700, top)
    b = place(client, auth_headers, night, "B#2", 1700, top)
    opened = start(client, auth_headers, night["id"], a, b)
    assert opened.status_code == 201, opened.text
    gone = leave(client, auth_headers, night["id"], a)
    row = only(gone, top)["played"][0]
    assert row["forfeit"] is True

    resent = flip(
        client, auth_headers, night["id"], row["series_id"], row["winner_side"]
    )
    turned = flip(
        client, auth_headers, night["id"], row["series_id"], 3 - row["winner_side"]
    )

    assert only(resent, top)["played"][0]["forfeit"] is True
    assert crowned(resent, top) == b
    assert only(turned, top)["played"][0]["forfeit"] is False
    assert only(turned, top)["played"][0]["winner"]["entrant_id"] == a


def test_a_crowned_race_that_leaves_the_table_passes_the_crown_to_his_other_race(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    """The series on the table comes off with no result and nobody moves in line."""
    night = open_night(client, auth_headers)
    top = bracket_ids(night)[0]
    user_a = two_races("A#1", 1700)
    a_hu = place_user(client, auth_headers, night, user_a, top)
    a_ne = place_user(client, auth_headers, night, user_a, top, race="NE")
    b = place(client, auth_headers, night, "B#2", 1700, top)
    p = place(client, auth_headers, night, "P#3", 1700, top)
    first = play(client, auth_headers, night["id"], a_hu, b)
    opened = start(client, auth_headers, night["id"], a_hu, p)
    assert opened.status_code == 201, opened.text

    gone = leave(client, auth_headers, night["id"], a_hu)

    bracket = only(gone, top)
    assert bracket["king_entrant_id"] == a_ne
    assert bracket["open_series"] is None
    assert [row["series_id"] for row in bracket["played"]] == [
        row["series_id"] for row in only(first, top)["played"]
    ]
    assert gone["series_count"] == 1
    assert line(gone, top) == [[p], [b]]


def test_a_crowned_race_with_no_other_race_forfeits_at_the_table(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    """With no other race of the king in the bracket, the other side wins the crown."""
    night = open_night(client, auth_headers)
    top = bracket_ids(night)[0]
    a = place(client, auth_headers, night, "A#1", 1700, top)
    b = place(client, auth_headers, night, "B#2", 1700, top)
    p = place(client, auth_headers, night, "P#3", 1700, top)
    play(client, auth_headers, night["id"], a, b)
    opened = start(client, auth_headers, night["id"], a, p)
    assert opened.status_code == 201, opened.text

    gone = leave(client, auth_headers, night["id"], a)

    newest = only(gone, top)["played"][0]
    assert (newest["forfeit"], newest["winner"]["entrant_id"]) == (True, p)
    assert crowned(gone, top) == p


def test_the_challenger_who_leaves_the_table_forfeits_to_a_king_with_two_races(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    """Only the crowned race passes the crown; the other side still forfeits."""
    night = open_night(client, auth_headers)
    top = bracket_ids(night)[0]
    user_a = two_races("A#1", 1700)
    a_hu = place_user(client, auth_headers, night, user_a, top)
    place_user(client, auth_headers, night, user_a, top, race="NE")
    b = place(client, auth_headers, night, "B#2", 1700, top)
    p = place(client, auth_headers, night, "P#3", 1700, top)
    play(client, auth_headers, night["id"], a_hu, b)
    opened = start(client, auth_headers, night["id"], a_hu, p)
    assert opened.status_code == 201, opened.text

    gone = leave(client, auth_headers, night["id"], p)

    newest = only(gone, top)["played"][0]
    assert (newest["forfeit"], newest["winner"]["entrant_id"]) == (True, a_hu)
    assert newest["throne"] == "held"
    assert crowned(gone, top) == a_hu
