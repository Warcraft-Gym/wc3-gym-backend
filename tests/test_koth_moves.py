"""A KOTH row that changes bracket, leaves or comes back.

Each test pins one rule: a move by hand is a move, never a copy, and empties a
throne without a forfeit; a king pointer never names a row of another bracket;
put back returns only the row that left; a king who withdraws one race keeps
the crown on his other race in that bracket; an erase deletes only a row no
series names and moves no other row.
"""

from typing import Any

import pytest
from httpx2 import Client
from sqlmodel import col, select

from app.core.db import Session
from app.models.base import ident
from app.models.enums import Race
from app.models.event_division import EventDivision
from app.models.event_entrant import EventEntrant
from app.models.series import Series
from app.models.series_side import SeriesSide
from app.models.user import User
from app.models.w3c_stats import W3CStats
from tests.test_awards import awarded
from tests.test_koth import silent_w3c
from tests.test_koth_live import (
    board,
    bracket_ids,
    chat,
    crowned,
    king_of,
    only,
    place,
    place_user,
    play,
    set_bounds,
    start,
)
from tests.test_koth_night import LATER, enrol, entrants, open_night

# Every signup asks W3Champions, so each test here answers for it
pytestmark = pytest.mark.usefixtures("quiet_w3c")


def move(
    client: Client,
    headers: dict[str, str],
    night_id: int,
    entrant_id: int,
    division_id: int,
) -> Any:  # noqa: ANN401
    return client.put(
        f"/koth/nights/{night_id}/entrants/{entrant_id}/bracket",
        json={"division_id": division_id},
        headers=headers,
    )


def two_races(tag: str, mmr: int) -> int:
    """One player rated on Human and on Night Elf."""
    user_id = enrol(tag, mmr)
    with Session.begin() as session:
        session.add(
            W3CStats(user_id=user_id, race=Race.NE, wc3_season=20, games=50, mmr=mmr)
        )
    return user_id


def line(payload: dict[str, Any], division_id: int) -> list[list[int]]:
    """The line of a bracket, one list of race rows per seat."""
    return [
        [row["entrant_id"] for row in seat["rows"]]
        for seat in only(payload, division_id)["queue"]
    ]


def stored_king(division_id: int) -> int | None:
    """The crown as the bracket row stores it."""
    with Session.begin() as session:
        division = session.get(EventDivision, division_id)
        assert division is not None
        return division.king_entrant_id


def user_of(client: Client, night_id: int, entrant_id: int) -> int:
    return next(
        row["user"]["id"]
        for row in entrants(client, night_id)
        if row["id"] == entrant_id
    )


def erase(
    client: Client, headers: dict[str, str], night_id: int, entrant_id: int
) -> Any:  # noqa: ANN401
    return client.post(
        f"/koth/nights/{night_id}/entrants/{entrant_id}/erase", headers=headers
    )


def held(night_id: int) -> dict[int, tuple[Any, ...]]:
    """Every row of the night: bracket, seed, placement mark, rating, leave stamp."""
    with Session.begin() as session:
        return {
            ident(row): (
                row.division_id,
                row.seed,
                row.manual_placement,
                row.mmr_at_seed,
                row.withdrawn_at,
            )
            for row in session.scalars(
                select(EventEntrant).where(col(EventEntrant.event_id) == night_id)
            )
        }


def test_a_moved_row_stands_last_and_no_new_bound_moves_it_back(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    """A rated row moved up a bracket is placed by hand, so the cut leaves it."""
    night = open_night(client, auth_headers)
    top, middle, _ = bracket_ids(night)
    first = place(client, auth_headers, night, "Top#1", 1700, top)
    second = place(client, auth_headers, night, "Top#2", 1700, top)
    climber = chat(client, night, "Climb#1111", 1500)
    assert line(board(client, night["id"]), middle) == [[climber]]

    moved = move(client, auth_headers, night["id"], climber, top)

    assert moved.status_code == 200, moved.text
    assert line(moved.json(), top) == [[first], [second], [climber]]
    assert only(moved.json(), middle)["queue"] == []
    row = next(one for one in entrants(client, night["id"]) if one["id"] == climber)
    assert row["manual_placement"] is True
    cut = set_bounds(client, auth_headers, night, [1650, 1400, 0])
    assert cut.status_code == 200, cut.text
    assert line(cut.json(), top) == [[first], [second], [climber]]


def test_a_move_refuses_a_series_a_row_that_left_and_a_closed_night(
    client: Client,
    auth_headers: dict[str, str],
    member: Any,  # noqa: ANN401
    seeded: dict[str, Any],
) -> None:
    night = open_night(client, auth_headers)
    top, middle, _ = bracket_ids(night)
    playing = place(client, auth_headers, night, "Play#1", 1700, top)
    rival = place(client, auth_headers, night, "Play#2", 1700, top)
    gone = place(client, auth_headers, night, "Gone#3", 1700, top)
    assert start(client, auth_headers, night["id"], playing, rival).status_code == 201
    removed = client.delete(
        f"/koth/nights/{night['id']}/entrants/{gone}", headers=auth_headers
    )
    assert removed.status_code == 200, removed.text
    path = f"/koth/nights/{night['id']}/entrants/{rival}/bracket"
    assert client.put(path, json={"division_id": middle}).status_code == 401
    assert (
        client.put(path, json={"division_id": middle}, headers=member("7")).status_code
        == 403
    )

    busy = move(client, auth_headers, night["id"], playing, middle)
    assert busy.status_code == 409, busy.text
    assert busy.json()["error"] == "Finish or cancel his series first"
    left = move(client, auth_headers, night["id"], gone, middle)
    assert left.status_code == 400, left.text
    assert left.json()["error"] == "Put the player back before moving him"

    client.post(f"/koth/nights/{night['id']}/close", headers=auth_headers)
    closed = move(client, auth_headers, night["id"], rival, middle)
    assert closed.status_code == 400, closed.text
    assert closed.json()["error"] == "The event is closed"

    later = open_night(client, auth_headers, starts_at=LATER)
    other = place(client, auth_headers, later, "Next#4", 1700, bracket_ids(later)[0])
    foreign = move(client, auth_headers, later["id"], other, middle)
    assert foreign.status_code == 400, foreign.text
    assert move(client, auth_headers, later["id"], rival, middle).status_code == 404


def test_a_king_who_moves_leaves_the_throne_empty_and_his_other_race_last(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    """No forfeit is written; his seat in the old bracket joins the end of it."""
    night = open_night(client, auth_headers)
    top, middle, _ = bracket_ids(night)
    user_id = two_races("Duo#1", 1700)
    human = place_user(client, auth_headers, night, user_id, top)
    elf = place_user(client, auth_headers, night, user_id, top, race="NE")
    beaten = place(client, auth_headers, night, "Beat#2", 1700, top)
    waiting = place(client, auth_headers, night, "Wait#3", 1700, top)
    played = play(client, auth_headers, night["id"], human, beaten)
    assert crowned(played, top) == human

    moved = move(client, auth_headers, night["id"], human, middle)

    assert moved.status_code == 200, moved.text
    payload = moved.json()
    assert king_of(payload, top) is None
    assert stored_king(top) is None
    assert payload["series_count"] == 1
    assert line(payload, top) == [[waiting], [beaten], [elf]]
    assert king_of(payload, middle) is None
    assert line(payload, middle) == [[human]]


def test_a_seat_keeps_its_place_when_one_of_its_races_moves(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    night = open_night(client, auth_headers)
    top, middle, _ = bracket_ids(night)
    first = place(client, auth_headers, night, "Ahead#1", 1700, top)
    user_id = two_races("Duo#2", 1700)
    human = place_user(client, auth_headers, night, user_id, top)
    elf = place_user(client, auth_headers, night, user_id, top, race="NE")
    last = place(client, auth_headers, night, "Behind#3", 1700, top)

    moved = move(client, auth_headers, night["id"], human, middle)

    assert moved.status_code == 200, moved.text
    assert line(moved.json(), top) == [[first], [elf], [last]]
    assert line(moved.json(), middle) == [[human]]


def test_the_shared_move_of_a_king_clears_the_crown_he_wore(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    """A row that comes back to his bracket is no king, so the close pays no Champion."""
    night = open_night(client, auth_headers)
    top, middle, _ = bracket_ids(night)
    king = place(client, auth_headers, night, "Crown#1", 1700, top)
    rival = place(client, auth_headers, night, "Rival#2", 1700, top)
    # The rival wins, then the admin hands the crown over: the king has no win
    play(client, auth_headers, night["id"], king, rival, winner=2)
    passed = client.put(
        f"/koth/nights/{night['id']}/brackets/{top}/crown",
        json={"entrant_id": king},
        headers=auth_headers,
    )
    assert passed.status_code == 200, passed.text

    away = client.put(
        f"/events/{night['id']}/entrants/{king}",
        json={"division_id": middle},
        headers=auth_headers,
    )

    assert away.status_code == 200, away.text
    assert stored_king(top) is None
    back = client.put(
        f"/events/{night['id']}/entrants/{king}",
        json={"division_id": top},
        headers=auth_headers,
    )
    assert back.status_code == 200, back.text
    assert king_of(board(client, night["id"]), top) is None
    closed = client.post(f"/koth/nights/{night['id']}/close", headers=auth_headers)
    assert closed.status_code == 200, closed.text
    assert awarded(night["id"]) == [
        (user_of(client, night["id"], rival), 2, "Runner-up"),
        (user_of(client, night["id"], king), 3, "Third"),
    ]


def test_put_back_returns_one_race_and_the_seat_keeps_its_place(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    night = open_night(client, auth_headers)
    top = bracket_ids(night)[0]
    first = place(client, auth_headers, night, "Ahead#1", 1700, top)
    user_id = two_races("Duo#3", 1700)
    human = place_user(client, auth_headers, night, user_id, top)
    elf = place_user(client, auth_headers, night, user_id, top, race="NE")
    last = place(client, auth_headers, night, "Behind#3", 1700, top)
    removed = client.delete(
        f"/koth/nights/{night['id']}/entrants/{human}", headers=auth_headers
    )
    assert removed.status_code == 200, removed.text

    back = client.post(
        f"/koth/nights/{night['id']}/entrants/{human}/restore", headers=auth_headers
    )

    assert back.status_code == 200, back.text
    assert line(back.json(), top) == [[first], [elf, human], [last]]
    assert only(back.json(), top)["left"] == []


def test_put_back_of_one_of_two_races_that_left_joins_the_end(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    night = open_night(client, auth_headers)
    top = bracket_ids(night)[0]
    user_id = two_races("Duo#4", 1700)
    human = place_user(client, auth_headers, night, user_id, top)
    elf = place_user(client, auth_headers, night, user_id, top, race="NE")
    first = place(client, auth_headers, night, "Stay#1", 1700, top)
    second = place(client, auth_headers, night, "Stay#2", 1700, top)
    for row in (human, elf):
        removed = client.delete(
            f"/koth/nights/{night['id']}/entrants/{row}", headers=auth_headers
        )
        assert removed.status_code == 200, removed.text

    back = client.post(
        f"/koth/nights/{night['id']}/entrants/{elf}/restore", headers=auth_headers
    )

    assert back.status_code == 200, back.text
    assert line(back.json(), top) == [[first], [second], [elf]]
    assert [row["entrant_id"] for row in only(back.json(), top)["left"]] == [human]


def test_put_back_refuses_a_row_that_has_not_left(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    night = open_night(client, auth_headers)
    here = place(client, auth_headers, night, "Here#1", 1700, bracket_ids(night)[0])

    resp = client.post(
        f"/koth/nights/{night['id']}/entrants/{here}/restore", headers=auth_headers
    )

    assert resp.status_code == 400, resp.text
    assert resp.json()["error"] == "Here has not left"


def test_a_leave_reads_a_crown_on_a_row_of_another_bracket_as_empty(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    """A crown left on a row that stands in another bracket is empty; a leave forfeits nothing."""
    night = open_night(client, auth_headers)
    top, middle, _ = bracket_ids(night)
    king = chat(client, night, "Rise#1111", 1500)
    rival = chat(client, night, "Stay#2222", 1500)
    play(client, auth_headers, night["id"], king, rival)
    place(client, auth_headers, night, "Top#3", 1700, top)
    # No route leaves a crown behind, so the row is moved under it directly
    with Session.begin() as session:
        row = session.get(EventEntrant, king)
        assert row is not None
        row.division_id = top
    assert stored_king(middle) == king

    left = client.delete(
        f"/koth/nights/{night['id']}/entrants/{king}", headers=auth_headers
    )

    assert left.status_code == 200, left.text
    assert left.json()["series_count"] == 1
    assert king_of(left.json(), top) is None
    assert stored_king(middle) is None


@pytest.mark.parametrize("door", ["player", "admin"])
def test_a_king_who_withdraws_one_race_keeps_the_crown_on_the_other(
    client: Client,
    auth_headers: dict[str, str],
    member: Any,  # noqa: ANN401
    seeded: dict[str, Any],
    door: str,
) -> None:
    """The player's own withdraw and the admin remove pass the crown, no forfeit."""
    night = open_night(client, auth_headers)
    top = bracket_ids(night)[0]
    user_id = two_races("Duo#5", 1700)
    human = place_user(client, auth_headers, night, user_id, top)
    elf = place_user(client, auth_headers, night, user_id, top, race="NE")
    beaten = place(client, auth_headers, night, "Beat#6", 1700, top)
    waiting = place(client, auth_headers, night, "Wait#7", 1700, top)
    play(client, auth_headers, night["id"], human, beaten)
    before = line(board(client, night["id"]), top)
    assert before == [[waiting], [beaten]]

    if door == "player":
        with Session.begin() as session:
            user = session.get(User, user_id)
            assert user is not None
            user.discordId = "9101"
        gone = client.delete(
            f"/events/{night['id']}/entrants/me",
            params={"race": "HU"},
            headers=member("9101"),
        )
        assert gone.status_code == 204, gone.text
    else:
        gone = client.delete(
            f"/koth/nights/{night['id']}/entrants/{human}", headers=auth_headers
        )
        assert gone.status_code == 200, gone.text

    payload = board(client, night["id"])
    assert crowned(payload, top) == elf
    assert king_of(payload, top) == user_id
    assert payload["series_count"] == 1
    assert line(payload, top) == before
    assert [row["entrant_id"] for row in only(payload, top)["left"]] == [human]


def test_a_king_whose_other_race_is_in_another_bracket_forfeits_as_before(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    """The crown passes only to a row of the same bracket; else the first in line."""
    night = open_night(client, auth_headers)
    top, middle, _ = bracket_ids(night)
    user_id = two_races("Duo#8", 1700)
    human = place_user(client, auth_headers, night, user_id, top)
    elf = place_user(client, auth_headers, night, user_id, middle, race="NE")
    beaten = place(client, auth_headers, night, "Beat#9", 1700, top)
    waiting = place(client, auth_headers, night, "Wait#10", 1700, top)
    play(client, auth_headers, night["id"], human, beaten)

    left = client.delete(
        f"/koth/nights/{night['id']}/entrants/{human}", headers=auth_headers
    )

    assert left.status_code == 200, left.text
    payload = left.json()
    assert crowned(payload, top) == waiting
    assert only(payload, top)["played"][0]["forfeit"] is True
    assert line(payload, middle) == [[elf]]


def test_an_erase_deletes_a_row_no_series_names_and_moves_no_other(
    client: Client,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    seeded: dict[str, Any],
) -> None:
    """A live, a left and an unplaced row go; the line, the seeds and the crowns stay."""
    silent_w3c(monkeypatch)
    night = open_night(client, auth_headers)
    top, middle, _ = bracket_ids(night)
    king = place(client, auth_headers, night, "King#1", 1700, top)
    beaten = place(client, auth_headers, night, "Beat#2", 1700, top)
    mistake = place(client, auth_headers, night, "Test#3", 1700, top)
    waiting = place(client, auth_headers, night, "Wait#4", 1700, top)
    climber = chat(client, night, "Climb#5555", 1500)
    gone = place(client, auth_headers, night, "Gone#6", 1500, middle)
    stray = client.post(
        f"/events/{night['id']}/entrants/admin",
        json={"user_id": enrol("Stray#7", 1200), "race": "OC"},
        headers=auth_headers,
    )
    assert stray.status_code == 201, stray.text
    play(client, auth_headers, night["id"], king, beaten)
    left = client.delete(
        f"/koth/nights/{night['id']}/entrants/{gone}", headers=auth_headers
    )
    assert left.status_code == 200, left.text
    assert [row["entrant_id"] for row in only(left.json(), middle)["left"]] == [gone]
    erased = [mistake, gone, stray.json()["id"]]
    before = held(night["id"])
    crowns = [stored_king(division) for division in bracket_ids(night)]

    for row in erased:
        resp = erase(client, auth_headers, night["id"], row)
        assert resp.status_code == 200, resp.text

    payload = resp.json()
    assert payload["entrant_count"] == 4
    assert payload["unplaced"] == []
    assert only(payload, middle)["left"] == []
    assert line(payload, top) == [[waiting], [beaten]]
    assert line(payload, middle) == [[climber]]
    assert crowned(payload, top) == king
    assert held(night["id"]) == {
        key: value for key, value in before.items() if key not in erased
    }
    assert [stored_king(division) for division in bracket_ids(night)] == crowns


def test_an_erase_refuses_a_side_of_any_series_of_the_night(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    """A series on the table, played or forfeit keeps both its sides on the record."""
    night = open_night(client, auth_headers)
    top = bracket_ids(night)[0]
    winner = place(client, auth_headers, night, "Won#1", 1700, top)
    loser = place(client, auth_headers, night, "Lost#2", 1700, top)
    quitter = place(client, auth_headers, night, "Quit#3", 1700, top)
    rival = place(client, auth_headers, night, "Rival#4", 1700, top)
    first = place(client, auth_headers, night, "Table#5", 1700, top)
    second = place(client, auth_headers, night, "Side#6", 1700, top)
    play(client, auth_headers, night["id"], winner, loser)
    assert start(client, auth_headers, night["id"], quitter, rival).status_code == 201
    forfeit = client.delete(
        f"/koth/nights/{night['id']}/entrants/{quitter}", headers=auth_headers
    )
    assert forfeit.status_code == 200, forfeit.text
    assert only(forfeit.json(), top)["played"][0]["forfeit"] is True
    assert start(client, auth_headers, night["id"], first, second).status_code == 201
    before = held(night["id"])

    for row, name in (
        (winner, "Won"),
        (loser, "Lost"),
        (quitter, "Quit"),
        (rival, "Rival"),
        (second, "Side"),
    ):
        resp = erase(client, auth_headers, night["id"], row)
        assert resp.status_code == 400, resp.text
        assert resp.json()["error"] == (
            f"{name} has a series in this event, so the signup stays on the record"
        )

    assert held(night["id"]) == before


def test_an_erase_of_a_king_crowned_by_hand_empties_the_throne(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    night = open_night(client, auth_headers)
    top = bracket_ids(night)[0]
    king = place(client, auth_headers, night, "Hand#1", 1700, top)
    other = place(client, auth_headers, night, "Other#2", 1700, top)
    passed = client.put(
        f"/koth/nights/{night['id']}/brackets/{top}/crown",
        json={"entrant_id": king},
        headers=auth_headers,
    )
    assert passed.status_code == 200, passed.text
    assert stored_king(top) == king

    resp = erase(client, auth_headers, night["id"], king)

    assert resp.status_code == 200, resp.text
    bracket = only(resp.json(), top)
    assert bracket["king_entrant_id"] is None
    assert bracket["king"] is None
    assert stored_king(top) is None
    assert line(resp.json(), top) == [[other]]


def test_an_erase_refuses_a_closed_night_another_night_and_a_non_admin(
    client: Client,
    auth_headers: dict[str, str],
    member: Any,  # noqa: ANN401
    seeded: dict[str, Any],
) -> None:
    night = open_night(client, auth_headers)
    row = place(client, auth_headers, night, "Stay#1", 1700, bracket_ids(night)[0])
    path = f"/koth/nights/{night['id']}/entrants/{row}/erase"
    assert client.post(path).status_code == 401
    assert client.post(path, headers=member("7")).status_code == 403

    client.post(f"/koth/nights/{night['id']}/close", headers=auth_headers)
    closed = erase(client, auth_headers, night["id"], row)
    assert closed.status_code == 400, closed.text
    assert closed.json()["error"] == "The event is closed"

    later = open_night(client, auth_headers, starts_at=LATER)
    assert erase(client, auth_headers, later["id"], row).status_code == 404
    assert row in {one["id"] for one in entrants(client, night["id"])}


def test_an_erase_refuses_a_row_a_seat_of_another_series_names(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    """A lobby with no stage seats a row of any event, so the seat keeps it."""
    night = open_night(client, auth_headers)
    top = bracket_ids(night)[0]
    seated = place(client, auth_headers, night, "Lobby#1", 1700, top)
    other = place(client, auth_headers, night, "Lobby#2", 1700, top)
    # A series of no round with two empty seats, as the season import writes a 2v2
    with Session.begin() as session:
        lobby = Series(host_player_id=user_of(client, night["id"], seated))
        session.add(lobby)
        session.flush()
        session.add_all(
            [SeriesSide(series_id=ident(lobby), side_no=side) for side in (1, 2)]
        )
        lobby_id = ident(lobby)
    seats = client.put(
        f"/series/{lobby_id}/sides",
        json={"entrant_ids": [seated, other]},
        headers=auth_headers,
    )
    assert seats.status_code == 200, seats.text

    resp = erase(client, auth_headers, night["id"], seated)

    assert resp.status_code == 400, resp.text
    assert resp.json()["error"] == (
        "Lobby holds a seat in another series, so the signup stays on the record"
    )
    assert seated in {one["id"] for one in entrants(client, night["id"])}
