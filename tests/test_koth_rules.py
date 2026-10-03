"""The KOTH line and crown rules an admin meets while fixing a running night.

Each test pins one rule: a queue write reorders only the rows it names, a
result sent again keeps its kind, a crowned race that leaves the table passes
the crown to another race of the player with no forfeit, and a crown changed
by hand or by a leave or a move is an event at its place in the order of
play, so every fix crowns by the walk from it.
"""

from typing import Any

from httpx2 import Client

from tests.test_koth_live import (
    add_result,
    board,
    bracket_ids,
    crowned,
    flip,
    only,
    place,
    place_user,
    play,
    played_ids,
    remove,
    start,
)
from tests.test_koth_moves import line, move, two_races
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


def labels(payload: dict[str, Any], division_id: int) -> list[str]:
    """What each played series did to the crown, oldest first."""
    return [row["throne"] for row in reversed(only(payload, division_id)["played"])]


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


def four(
    client: Client, headers: dict[str, str], night: dict[str, Any], top: int
) -> tuple[int, int, int, int]:
    """Four players A, B, C and D in one bracket, A first in line."""
    return (
        place(client, headers, night, "A#1", 1700, top),
        place(client, headers, night, "B#2", 1700, top),
        place(client, headers, night, "C#3", 1700, top),
        place(client, headers, night, "D#4", 1700, top),
    )


def test_a_step_down_then_a_turned_result_crowns_the_new_winner(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    """A beat B, the throne is emptied, C beat D takes it; turned, D is king."""
    night = open_night(client, auth_headers)
    top = bracket_ids(night)[0]
    a, b, c, d = four(client, auth_headers, night, top)
    play(client, auth_headers, night["id"], a, b)
    set_crown(client, auth_headers, night["id"], top, None)
    taken = play(client, auth_headers, night["id"], c, d)
    assert crowned(taken, top) == c
    assert labels(taken, top) == ["moved", "moved"]

    payload = flip(client, auth_headers, night["id"], played_ids(taken, top)[-1], 2)

    assert crowned(payload, top) == d
    assert labels(payload, top) == ["moved", "moved"]


def test_a_hand_pass_then_a_turned_later_result_crowns_by_the_walk_from_the_pass(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    """A beat B, the crown goes to C, C beat D, E beat C; turned, C is king."""
    night = open_night(client, auth_headers)
    top = bracket_ids(night)[0]
    a, b, c, d = four(client, auth_headers, night, top)
    e = place(client, auth_headers, night, "E#5", 1700, top)
    play(client, auth_headers, night["id"], a, b)
    set_crown(client, auth_headers, night["id"], top, c)
    play(client, auth_headers, night["id"], c, d)
    taken = play(client, auth_headers, night["id"], c, e, winner=2)
    assert crowned(taken, top) == e
    assert labels(taken, top) == ["moved", "held", "moved"]

    payload = flip(client, auth_headers, night["id"], played_ids(taken, top)[-1], 1)

    assert crowned(payload, top) == c
    assert labels(payload, top) == ["moved", "held", "held"]


def test_a_step_down_then_a_removed_result_leaves_the_throne_empty(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    """Without the series that took the emptied throne, nobody wears the crown."""
    night = open_night(client, auth_headers)
    top = bracket_ids(night)[0]
    a, b, c, d = four(client, auth_headers, night, top)
    play(client, auth_headers, night["id"], a, b)
    set_crown(client, auth_headers, night["id"], top, None)
    taken = play(client, auth_headers, night["id"], c, d)

    payload = remove(client, auth_headers, night["id"], played_ids(taken, top)[-1])

    assert crowned(payload, top) is None


def test_a_king_who_left_with_nobody_free_then_a_turned_result_crowns_the_new_winner(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    """A leave that empties the throne is an event, so the next result takes it."""
    night = open_night(client, auth_headers)
    top = bracket_ids(night)[0]
    a = place(client, auth_headers, night, "A#1", 1700, top)
    b = place(client, auth_headers, night, "B#2", 1700, top)
    play(client, auth_headers, night["id"], a, b)
    leave(client, auth_headers, night["id"], b)
    gone = leave(client, auth_headers, night["id"], a)
    assert crowned(gone, top) is None
    c = place(client, auth_headers, night, "C#3", 1700, top)
    d = place(client, auth_headers, night, "D#4", 1700, top)
    taken = play(client, auth_headers, night["id"], c, d)
    assert crowned(taken, top) == c

    payload = flip(client, auth_headers, night["id"], played_ids(taken, top)[-1], 2)

    assert crowned(payload, top) == d


def test_a_step_down_then_an_added_result_takes_the_empty_throne(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    """An added result lands after the step down, as a played series would."""
    night = open_night(client, auth_headers)
    top = bracket_ids(night)[0]
    a, b, c, d = four(client, auth_headers, night, top)
    play(client, auth_headers, night["id"], a, b)
    set_crown(client, auth_headers, night["id"], top, None)

    added = add_result(client, auth_headers, night["id"], c, d)

    assert added.status_code == 201, added.text
    assert crowned(added.json(), top) == c
    assert labels(added.json(), top) == ["moved", "moved"]


def test_a_hand_pass_then_an_added_result_that_beats_the_king_crowns_its_winner(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    """The crown went to C by hand, so D beat C moves it to D."""
    night = open_night(client, auth_headers)
    top = bracket_ids(night)[0]
    a, b, c, d = four(client, auth_headers, night, top)
    play(client, auth_headers, night["id"], a, b)
    set_crown(client, auth_headers, night["id"], top, c)

    added = add_result(client, auth_headers, night["id"], d, c)

    assert added.status_code == 201, added.text
    assert crowned(added.json(), top) == d


def test_a_moved_king_then_a_turned_result_crowns_the_new_winner(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    """A king moved to another bracket leaves an empty throne at that place."""
    night = open_night(client, auth_headers)
    top, middle = bracket_ids(night)[0], bracket_ids(night)[1]
    a, b, c, d = four(client, auth_headers, night, top)
    play(client, auth_headers, night["id"], a, b)
    moved = move(client, auth_headers, night["id"], a, middle)
    assert moved.status_code == 200, moved.text
    assert crowned(moved.json(), top) is None
    taken = play(client, auth_headers, night["id"], c, d)
    assert crowned(taken, top) == c

    payload = flip(client, auth_headers, night["id"], played_ids(taken, top)[-1], 2)

    assert crowned(payload, top) == d


def test_a_race_swap_by_hand_is_no_crown_event(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    """The crown stays with the same player, so a turned result still moves it."""
    night = open_night(client, auth_headers)
    top = bracket_ids(night)[0]
    user_a = two_races("A#1", 1700)
    a_hu = place_user(client, auth_headers, night, user_a, top)
    a_ne = place_user(client, auth_headers, night, user_a, top, race="NE")
    b = place(client, auth_headers, night, "B#2", 1700, top)
    played = play(client, auth_headers, night["id"], a_hu, b)
    swapped = set_crown(client, auth_headers, night["id"], top, a_ne)
    assert only(swapped, top)["king_entrant_id"] == a_ne

    payload = flip(client, auth_headers, night["id"], played_ids(played, top)[-1], 2)

    assert crowned(payload, top) == b


def test_a_series_after_a_removed_result_still_plays_after_the_crown_event(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    """A step down stays before the next series when the result before it goes."""
    night = open_night(client, auth_headers)
    top = bracket_ids(night)[0]
    a, b, c, d = four(client, auth_headers, night, top)
    play(client, auth_headers, night["id"], a, b)
    taken = play(client, auth_headers, night["id"], a, c, winner=2)
    set_crown(client, auth_headers, night["id"], top, None)
    emptied = remove(client, auth_headers, night["id"], played_ids(taken, top)[-1])
    assert crowned(emptied, top) is None

    after = play(client, auth_headers, night["id"], d, b)
    assert crowned(after, top) == d
    assert labels(after, top) == ["moved", "moved"]
    payload = flip(client, auth_headers, night["id"], played_ids(after, top)[-1], 2)

    assert crowned(payload, top) == b


def test_clearing_a_night_drops_its_crown_events(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    """After a clear, a hand pass of the test run no longer touches the crown."""
    night = open_night(client, auth_headers)
    top = bracket_ids(night)[0]
    a, b, c, d = four(client, auth_headers, night, top)
    play(client, auth_headers, night["id"], a, b)
    set_crown(client, auth_headers, night["id"], top, c)
    cleared = client.delete(f"/koth/nights/{night['id']}/series", headers=auth_headers)
    assert cleared.status_code == 200, cleared.text

    added = add_result(client, auth_headers, night["id"], d, b)

    assert added.status_code == 201, added.text
    assert crowned(added.json(), top) == d
    assert labels(added.json(), top) == ["moved"]


def test_a_fix_passes_the_crown_to_the_other_race_of_a_king_whose_race_left(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    """The crown is the player's, so a walk that ends on a race that left crowns
    his other race."""
    night = open_night(client, auth_headers)
    top = bracket_ids(night)[0]
    user_a = two_races("A#1", 1700)
    a_hu = place_user(client, auth_headers, night, user_a, top)
    a_ne = place_user(client, auth_headers, night, user_a, top, race="NE")
    b = place(client, auth_headers, night, "B#2", 1700, top)
    c = place(client, auth_headers, night, "C#3", 1700, top)
    play(client, auth_headers, night["id"], a_hu, b)
    passed = leave(client, auth_headers, night["id"], a_hu)
    assert crowned(passed, top) == a_ne
    taken = play(client, auth_headers, night["id"], a_ne, c, winner=2)
    assert crowned(taken, top) == c

    payload = remove(client, auth_headers, night["id"], played_ids(taken, top)[-1])

    assert crowned(payload, top) == a_ne


def test_a_throne_a_fix_empties_for_a_player_who_left_is_taken_by_the_next_result(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    """A fix that crowns a player who left empties the throne from that place on."""
    night = open_night(client, auth_headers)
    top = bracket_ids(night)[0]
    a, b, c, d = four(client, auth_headers, night, top)
    play(client, auth_headers, night["id"], a, b)
    taken = play(client, auth_headers, night["id"], a, c, winner=2)
    leave(client, auth_headers, night["id"], a)
    emptied = remove(client, auth_headers, night["id"], played_ids(taken, top)[-1])
    assert crowned(emptied, top) is None

    after = play(client, auth_headers, night["id"], d, b)
    assert labels(after, top) == ["moved", "moved"]
    payload = flip(client, auth_headers, night["id"], played_ids(after, top)[-1], 2)

    assert crowned(payload, top) == b
