"""A KOTH night run by hand: the admin starts every series and enters the result.

The assertions read the board, because the board is what the run page and the
public dashboard draw. Each test pins one rule of the night: who wears the
crown, who stands where in line, and what the night refuses.
"""

from typing import Any

import pytest
from httpx2 import Client

from app.core.db import Session
from app.models.base import ident
from app.models.enums import Race
from app.models.series_game import DBSeriesGame
from app.models.user import User
from app.models.w3c_stats import W3CStats
from app.services.koth import legacy
from tests.test_koth import silent_w3c
from tests.test_koth_night import enrol, entrants, open_night, sign_up
from tests.test_query_budget import count_statements

LATER = "2026-10-05T19:00:00Z"


def bracket_ids(night: dict[str, Any]) -> list[int]:
    """The brackets of the night, the strongest first."""
    return [row["id"] for row in night["divisions"]]


def place(
    client: Client,
    headers: dict[str, str],
    night: dict[str, Any],
    tag: str,
    mmr: int,
    division_id: int,
    race: str = "HU",
) -> int:
    """One player entered by an admin and put in one bracket by hand."""
    return place_user(
        client, headers, night, enrol(tag, mmr, Race(race)), division_id, race
    )


def place_user(
    client: Client,
    headers: dict[str, str],
    night: dict[str, Any],
    user_id: int,
    division_id: int,
    race: str = "HU",
) -> int:
    """One more race row for a player who already exists."""
    resp = client.post(
        f"/events/{night['id']}/entrants/admin",
        json={"user_id": user_id, "race": race},
        headers=headers,
    )
    assert resp.status_code == 201, resp.text
    entrant_id = resp.json()["id"]
    moved = client.put(
        f"/events/{night['id']}/entrants/{entrant_id}",
        json={"division_id": division_id},
        headers=headers,
    )
    assert moved.status_code == 200, moved.text
    return entrant_id


def start(
    client: Client, headers: dict[str, str], night_id: int, first: int, second: int
) -> Any:  # noqa: ANN401
    return client.post(
        f"/koth/nights/{night_id}/series",
        json={"entrant1_id": first, "entrant2_id": second},
        headers=headers,
    )


def board(client: Client, night_id: int) -> dict[str, Any]:
    resp = client.get(f"/koth/nights/{night_id}/board")
    assert resp.status_code == 200, resp.text
    return resp.json()


def only(payload: dict[str, Any], division_id: int) -> dict[str, Any]:
    """The one bracket of the board the test works in."""
    return next(row for row in payload["brackets"] if row["division_id"] == division_id)


def play(
    client: Client,
    headers: dict[str, str],
    night_id: int,
    first: int,
    second: int,
    winner: int = 1,
) -> dict[str, Any]:
    """Start a series between two rows and enter its result in one step."""
    opened = start(client, headers, night_id, first, second)
    assert opened.status_code == 201, opened.text
    series_id = _open_id(opened.json(), first)
    done = client.put(
        f"/koth/nights/{night_id}/series/{series_id}/result",
        json={"winner": winner},
        headers=headers,
    )
    assert done.status_code == 200, done.text
    return done.json()


def _open_id(payload: dict[str, Any], entrant_id: int) -> int:
    """The series the board shows on the table for the bracket of that row."""
    for row in payload["brackets"]:
        series = row["open_series"]
        if series and entrant_id in (
            series["side1"]["entrant_id"],
            series["side2"]["entrant_id"],
        ):
            return int(series["series_id"])
    raise AssertionError("no open series holds that row")


def king_of(payload: dict[str, Any], division_id: int) -> int | None:
    seat = only(payload, division_id)["king"]
    return seat["user_id"] if seat else None


def line_of(payload: dict[str, Any], division_id: int) -> list[int]:
    return [seat["user_id"] for seat in only(payload, division_id)["queue"]]


def test_the_first_series_of_a_bracket_crowns_its_winner(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    """A bracket with no king crowns whoever wins its first series."""
    night = open_night(client, auth_headers)
    top = bracket_ids(night)[0]
    first = place(client, auth_headers, night, "One#1", 1700, top)
    second = place(client, auth_headers, night, "Two#2", 1700, top)

    payload = play(client, auth_headers, night["id"], first, second)

    assert king_of(payload, top) is not None
    assert only(payload, top)["king"]["rows"][0]["entrant_id"] == first
    assert only(payload, top)["played"][0]["throne"] == "moved"


def test_the_crown_moves_when_the_king_plays_and_loses(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    """The reigning king keeps the crown until he loses a series himself."""
    night = open_night(client, auth_headers)
    top = bracket_ids(night)[0]
    king = place(client, auth_headers, night, "King#1", 1700, top)
    first = place(client, auth_headers, night, "First#2", 1700, top)
    challenger = place(client, auth_headers, night, "Next#3", 1700, top)
    crowned = play(client, auth_headers, night["id"], king, first)
    held = king_of(crowned, top)

    payload = play(client, auth_headers, night["id"], king, challenger, winner=2)

    assert king_of(payload, top) != held
    assert only(payload, top)["played"][0]["throne"] == "moved"


def test_a_side_game_leaves_the_crown_where_it_stands(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    """A series between two rows the king does not play changes no crown."""
    night = open_night(client, auth_headers)
    top = bracket_ids(night)[0]
    king = place(client, auth_headers, night, "Hold#1", 1700, top)
    beaten = place(client, auth_headers, night, "Beat#2", 1700, top)
    third = place(client, auth_headers, night, "Side#3", 1700, top)
    fourth = place(client, auth_headers, night, "Game#4", 1700, top)
    crowned = play(client, auth_headers, night["id"], king, beaten)

    payload = play(client, auth_headers, night["id"], third, fourth)

    assert king_of(payload, top) == king_of(crowned, top)
    assert only(payload, top)["played"][0]["throne"] == "none"


def test_stepping_down_empties_the_throne_and_the_next_result_crowns(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    """An empty throne is taken by the winner of the next series, whoever plays."""
    night = open_night(client, auth_headers)
    top = bracket_ids(night)[0]
    king = place(client, auth_headers, night, "Down#1", 1700, top)
    beaten = place(client, auth_headers, night, "Lost#2", 1700, top)
    third = place(client, auth_headers, night, "Take#3", 1700, top)
    fourth = place(client, auth_headers, night, "Over#4", 1700, top)
    play(client, auth_headers, night["id"], king, beaten)

    stepped = client.put(
        f"/koth/nights/{night['id']}/brackets/{top}/crown",
        json={"entrant_id": None},
        headers=auth_headers,
    )
    assert stepped.status_code == 200, stepped.text
    assert king_of(stepped.json(), top) is None

    payload = play(client, auth_headers, night["id"], third, fourth)

    assert only(payload, top)["king"]["rows"][0]["entrant_id"] == third


def test_an_admin_passes_the_crown_to_a_row_of_the_same_bracket(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    """The crown moves to the named row, and it never leaves its own bracket."""
    night = open_night(client, auth_headers)
    top, middle = bracket_ids(night)[0], bracket_ids(night)[1]
    king = place(client, auth_headers, night, "Pass#1", 1700, top)
    beaten = place(client, auth_headers, night, "Take#2", 1700, top)
    outside = place(client, auth_headers, night, "Else#3", 1500, middle)
    play(client, auth_headers, night["id"], king, beaten)

    passed = client.put(
        f"/koth/nights/{night['id']}/brackets/{top}/crown",
        json={"entrant_id": beaten},
        headers=auth_headers,
    )

    assert passed.status_code == 200, passed.text
    assert only(passed.json(), top)["king"]["rows"][0]["entrant_id"] == beaten
    refused = client.put(
        f"/koth/nights/{night['id']}/brackets/{top}/crown",
        json={"entrant_id": outside},
        headers=auth_headers,
    )
    assert refused.status_code == 400, refused.text


def test_a_king_who_was_removed_and_put_back_is_an_ordinary_row(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    """A row that left loses the crown and does not take it back on return."""
    night = open_night(client, auth_headers)
    top = bracket_ids(night)[0]
    king = place(client, auth_headers, night, "Gone#1", 1700, top)
    beaten = place(client, auth_headers, night, "Stay#2", 1700, top)
    play(client, auth_headers, night["id"], king, beaten)

    left = client.delete(
        f"/koth/nights/{night['id']}/entrants/{king}", headers=auth_headers
    )
    assert left.status_code == 200, left.text
    assert king_of(left.json(), top) is None

    back = client.post(
        f"/koth/nights/{night['id']}/entrants/{king}/restore", headers=auth_headers
    )

    assert back.status_code == 200, back.text
    assert king_of(back.json(), top) is None
    assert (
        line_of(back.json(), top)[-1] == only(back.json(), top)["queue"][-1]["user_id"]
    )


def test_changing_the_winner_moves_the_crown_and_the_line(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    """A corrected result crowns the other side and sends the other one last."""
    night = open_night(client, auth_headers)
    top = bracket_ids(night)[0]
    first = place(client, auth_headers, night, "Wrong#1", 1700, top)
    second = place(client, auth_headers, night, "Right#2", 1700, top)
    waiting = place(client, auth_headers, night, "Wait#3", 1700, top)
    played = play(client, auth_headers, night["id"], first, second)
    series_id = only(played, top)["played"][0]["series_id"]

    changed = client.put(
        f"/koth/nights/{night['id']}/series/{series_id}/result",
        json={"winner": 2},
        headers=auth_headers,
    )

    assert changed.status_code == 200, changed.text
    payload = changed.json()
    assert only(payload, top)["king"]["rows"][0]["entrant_id"] == second
    line = [seat["rows"][0]["entrant_id"] for seat in only(payload, top)["queue"]]
    assert line == [waiting, first]


def test_the_loser_stands_last_in_line(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    """The beaten row goes to the end; the winner leaves the line as king."""
    night = open_night(client, auth_headers)
    top = bracket_ids(night)[0]
    first = place(client, auth_headers, night, "Won#1", 1700, top)
    second = place(client, auth_headers, night, "Lost#2", 1700, top)
    third = place(client, auth_headers, night, "Third#3", 1700, top)

    payload = play(client, auth_headers, night["id"], first, second)

    line = [seat["rows"][0]["entrant_id"] for seat in only(payload, top)["queue"]]
    assert line == [third, second]


def test_a_bracket_holds_one_series_on_the_table(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    """A second start answers 409 while the first series carries no result."""
    night = open_night(client, auth_headers)
    top = bracket_ids(night)[0]
    first = place(client, auth_headers, night, "Busy#1", 1700, top)
    second = place(client, auth_headers, night, "Busy#2", 1700, top)
    third = place(client, auth_headers, night, "Busy#3", 1700, top)
    fourth = place(client, auth_headers, night, "Busy#4", 1700, top)
    assert start(client, auth_headers, night["id"], first, second).status_code == 201

    second_start = start(client, auth_headers, night["id"], third, fourth)

    assert second_start.status_code == 409, second_start.text
    assert "series on the table" in second_start.json()["error"]


def test_a_start_refuses_two_rows_of_one_player(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    """A player who signed up on two races in one bracket plays nobody but others."""
    night = open_night(client, auth_headers)
    top = bracket_ids(night)[0]
    user_id = enrol("Both#1", 1700)
    with Session.begin() as session:
        session.add(
            W3CStats(user_id=user_id, race=Race.NE, wc3_season=20, games=50, mmr=1700)
        )
    human = place_user(client, auth_headers, night, user_id, top)
    elf = place_user(client, auth_headers, night, user_id, top, race="NE")

    refused = start(client, auth_headers, night["id"], human, elf)

    assert refused.status_code == 400, refused.text
    assert refused.json()["error"] == "A player cannot play himself"


def test_a_start_refuses_two_brackets_and_a_row_that_left(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    """Both rows play in one bracket, and a row that left plays nothing."""
    night = open_night(client, auth_headers)
    top, middle = bracket_ids(night)[0], bracket_ids(night)[1]
    first = place(client, auth_headers, night, "Here#1", 1700, top)
    other = place(client, auth_headers, night, "There#2", 1500, middle)
    second = place(client, auth_headers, night, "Here#3", 1700, top)

    assert start(client, auth_headers, night["id"], first, other).status_code == 400
    client.delete(f"/koth/nights/{night['id']}/entrants/{second}", headers=auth_headers)

    assert start(client, auth_headers, night["id"], first, second).status_code == 400


def test_the_queue_reorders_one_bracket_and_leaves_the_others(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    """The drag writes the seeds of its own bracket, first in line first."""
    night = open_night(client, auth_headers)
    top, middle = bracket_ids(night)[0], bracket_ids(night)[1]
    first = place(client, auth_headers, night, "Drag#1", 1700, top)
    second = place(client, auth_headers, night, "Drag#2", 1700, top)
    third = place(client, auth_headers, night, "Drag#3", 1700, top)
    other = place(client, auth_headers, night, "Keep#4", 1500, middle)

    moved = client.put(
        f"/koth/nights/{night['id']}/brackets/{top}/queue",
        json={"entrant_ids": [third, first, second]},
        headers=auth_headers,
    )

    assert moved.status_code == 200, moved.text
    line = [seat["rows"][0]["entrant_id"] for seat in only(moved.json(), top)["queue"]]
    assert line == [third, first, second]
    assert [
        seat["rows"][0]["entrant_id"] for seat in only(moved.json(), middle)["queue"]
    ] == [other]


def test_cancel_takes_an_unplayed_series_off_and_keeps_a_played_one(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    """An open series is deleted; a series that carries a result is not."""
    night = open_night(client, auth_headers)
    top = bracket_ids(night)[0]
    first = place(client, auth_headers, night, "Off#1", 1700, top)
    second = place(client, auth_headers, night, "Off#2", 1700, top)
    opened = start(client, auth_headers, night["id"], first, second)
    series_id = _open_id(opened.json(), first)

    gone = client.delete(
        f"/koth/nights/{night['id']}/series/{series_id}", headers=auth_headers
    )

    assert gone.status_code == 200, gone.text
    assert only(gone.json(), top)["open_series"] is None
    played = play(client, auth_headers, night["id"], first, second)
    kept = only(played, top)["played"][0]["series_id"]
    refused = client.delete(
        f"/koth/nights/{night['id']}/series/{kept}", headers=auth_headers
    )
    assert refused.status_code == 400, refused.text


def test_the_defender_shows_only_while_the_bracket_has_no_king(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    """The king of the last closed night is a hint on the same bracket, no rule."""
    first_night = open_night(client, auth_headers)
    top = bracket_ids(first_night)[0]
    champion = place(client, auth_headers, first_night, "Hold#1", 1700, top)
    rival = place(client, auth_headers, first_night, "Fell#2", 1700, top)
    play(client, auth_headers, first_night["id"], champion, rival)
    with Session() as session:
        holder = ident(session.scalars(_by_tag("Hold#1")).one())
        other = ident(session.scalars(_by_tag("Fell#2")).one())
    closed = client.post(
        f"/koth/nights/{first_night['id']}/close", headers=auth_headers
    )
    assert closed.status_code == 200, closed.text

    night = open_night(client, auth_headers, starts_at=LATER)
    tonight_top = bracket_ids(night)[0]
    back = place_user(client, auth_headers, night, holder, tonight_top)
    place_user(client, auth_headers, night, other, tonight_top)

    payload = board(client, night["id"])
    assert only(payload, tonight_top)["defender"]["entrant_id"] == back

    crowned = play(client, auth_headers, night["id"], back, back + 1)
    assert only(crowned, tonight_top)["defender"] is None


def test_closing_the_night_deletes_the_series_on_the_table(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    """The open series of every bracket goes, and the closed board still reads."""
    night = open_night(client, auth_headers)
    top = bracket_ids(night)[0]
    first = place(client, auth_headers, night, "Shut#1", 1700, top)
    second = place(client, auth_headers, night, "Shut#2", 1700, top)
    third = place(client, auth_headers, night, "Shut#3", 1700, top)
    play(client, auth_headers, night["id"], first, second)
    assert start(client, auth_headers, night["id"], first, third).status_code == 201

    closed = client.post(f"/koth/nights/{night['id']}/close", headers=auth_headers)

    assert closed.status_code == 200, closed.text
    payload = board(client, night["id"])
    assert payload["closed"] is True
    settled = client.get(f"/koth/nights/{night['id']}/board").headers["Cache-Control"]
    assert settled == "public, s-maxage=3600, stale-while-revalidate=86400"
    assert only(payload, top)["open_series"] is None
    assert only(payload, top)["king"]["rows"][0]["entrant_id"] == first
    assert len(only(payload, top)["played"]) == 1


def test_a_closed_night_takes_no_write(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    """Every live write of the night refuses once the night is closed."""
    night = open_night(client, auth_headers)
    top = bracket_ids(night)[0]
    first = place(client, auth_headers, night, "Late#1", 1700, top)
    second = place(client, auth_headers, night, "Late#2", 1700, top)
    client.post(f"/koth/nights/{night['id']}/close", headers=auth_headers)

    refused = start(client, auth_headers, night["id"], first, second)

    assert refused.status_code == 400, refused.text


def test_the_board_carries_the_night_and_its_edge_headers(
    client: Client,
    auth_headers: dict[str, str],
    seeded: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The header counts the night, and the read is cached at the edge."""
    silent_w3c(monkeypatch)
    night = open_night(client, auth_headers)
    top = bracket_ids(night)[0]
    first = place(client, auth_headers, night, "Head#1", 1700, top)
    place(client, auth_headers, night, "Head#2", 1700, top)
    unplaced = client.post(
        f"/events/{night['id']}/entrants/admin",
        json={"user_id": enrol("Wait#3", 1200), "race": "OC"},
        headers=auth_headers,
    )
    assert unplaced.status_code == 201, unplaced.text

    resp = client.get(f"/koth/nights/{night['id']}/board")

    assert resp.status_code == 200, resp.text
    assert resp.headers["Cache-Control"] == "public, s-maxage=15"  # live
    assert resp.headers["Access-Control-Allow-Origin"] == "*"
    payload = resp.json()
    assert payload["night_id"] == night["id"]
    assert payload["name"] == night["name"]
    assert payload["closed"] is False
    assert payload["entrant_count"] == 3
    assert payload["series_count"] == 0
    assert len(payload["brackets"]) == 3
    assert [row["entrant_id"] for row in payload["unplaced"]] == [unplaced.json()["id"]]
    assert payload["unplaced"][0]["mmr"] is None
    assert only(payload, top)["queue"][0]["rows"][0]["entrant_id"] == first
    same = client.get("/koth/board")
    assert same.json()["night_id"] == night["id"]


def test_the_board_of_thirty_rows_is_small_and_costs_a_fixed_read(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    """The dashboard polls this read, so it grows with no statement per row."""
    night = open_night(client, auth_headers)
    brackets = bracket_ids(night)
    rows = [
        place(client, auth_headers, night, f"Full#{number}", 1700, brackets[number % 3])
        for number in range(30)
    ]
    play(client, auth_headers, night["id"], rows[0], rows[3])

    with count_statements() as ten:
        small = client.get(f"/koth/nights/{night['id']}/board")
    for number in range(30, 60):
        place(client, auth_headers, night, f"More#{number}", 1700, brackets[number % 3])
    with count_statements() as sixty:
        client.get(f"/koth/nights/{night['id']}/board")

    assert small.status_code == 200, small.text
    # 30 rows and one played series read 3989 bytes over 10 statements
    assert len(small.content) < 5000
    assert ten[0] == sixty[0] == 10


def test_a_save_that_turns_no_result_around_leaves_the_crown(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    """A rematch moves the crown; saving a field of the older series moves nothing."""
    night = open_night(client, auth_headers)
    top = bracket_ids(night)[0]
    first = place(client, auth_headers, night, "Again#1", 1700, top)
    second = place(client, auth_headers, night, "Again#2", 1700, top)
    one = play(client, auth_headers, night["id"], first, second)
    series_id = only(one, top)["played"][0]["series_id"]
    rematch = play(client, auth_headers, night["id"], first, second, winner=2)
    crowned = king_of(rematch, top)

    saved = client.put(
        f"/series/{series_id}", json={"date_time": LATER}, headers=auth_headers
    )

    assert saved.status_code == 200, saved.text
    assert king_of(board(client, night["id"]), top) == crowned


def test_an_empty_throne_survives_a_save_of_an_old_series(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    """A king who stepped down takes no crown back when his series is saved again."""
    night = open_night(client, auth_headers)
    top = bracket_ids(night)[0]
    king = place(client, auth_headers, night, "Left#1", 1700, top)
    beaten = place(client, auth_headers, night, "Fell#2", 1700, top)
    played = play(client, auth_headers, night["id"], king, beaten)
    series_id = only(played, top)["played"][0]["series_id"]
    stepped = client.put(
        f"/koth/nights/{night['id']}/brackets/{top}/crown",
        json={"entrant_id": None},
        headers=auth_headers,
    )
    assert stepped.status_code == 200, stepped.text

    saved = client.put(
        f"/series/{series_id}", json={"date_time": LATER}, headers=auth_headers
    )

    assert saved.status_code == 200, saved.text
    assert king_of(board(client, night["id"]), top) is None


def test_the_public_board_hides_a_night_that_is_not_published(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    """A draft night is the admin's own, so the public read answers not found."""
    night = open_night(client, auth_headers)
    top = bracket_ids(night)[0]
    first = place(client, auth_headers, night, "Draft#1", 1700, top)
    second = place(client, auth_headers, night, "Draft#2", 1700, top)
    hidden = client.put(
        f"/events/{night['id']}", json={"published": False}, headers=auth_headers
    )
    assert hidden.status_code == 200, hidden.text

    resp = client.get(f"/koth/nights/{night['id']}/board")

    assert resp.status_code == 404, resp.text
    opened = start(client, auth_headers, night["id"], first, second)
    assert opened.status_code == 201, opened.text


def test_every_live_write_takes_an_admin_and_nobody_else(
    client: Client,
    auth_headers: dict[str, str],
    member: Any,  # noqa: ANN401
    seeded: dict[str, Any],
) -> None:
    """Each write of the night answers 401 with no token and 403 to a member."""
    night = open_night(client, auth_headers)
    top = bracket_ids(night)[0]
    first = place(client, auth_headers, night, "Shut#1", 1700, top)
    second = place(client, auth_headers, night, "Shut#2", 1700, top)
    writes = [
        ("post", f"/koth/nights/{night['id']}/series"),
        ("delete", f"/koth/nights/{night['id']}/series/1"),
        ("put", f"/koth/nights/{night['id']}/series/1/result"),
        ("put", f"/koth/nights/{night['id']}/brackets/{top}/queue"),
        ("put", f"/koth/nights/{night['id']}/brackets/{top}/crown"),
        ("put", f"/koth/nights/{night['id']}/bounds"),
        ("delete", f"/koth/nights/{night['id']}/entrants/{first}"),
        ("post", f"/koth/nights/{night['id']}/entrants/{first}/restore"),
    ]

    for method, path in writes:
        anonymous = client.request(method, path, json={})
        assert anonymous.status_code == 401, f"{path}: {anonymous.text}"
        refused = client.request(method, path, json={}, headers=member("7"))
        assert refused.status_code == 403, f"{path}: {refused.text}"

    payload = board(client, night["id"])
    assert payload["series_count"] == 0
    assert len(line_of(payload, top)) == 2
    assert only(payload, top)["left"] == []
    assert start(client, auth_headers, night["id"], first, second).status_code == 201


def test_the_king_loses_on_his_second_race_row_and_the_crown_moves(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    """The crown follows the player, so it moves on whichever race row he plays."""
    night = open_night(client, auth_headers)
    top = bracket_ids(night)[0]
    user_id = enrol("Two#1", 1700)
    with Session.begin() as session:
        session.add(
            W3CStats(user_id=user_id, race=Race.NE, wc3_season=20, games=50, mmr=1700)
        )
    human = place_user(client, auth_headers, night, user_id, top)
    elf = place_user(client, auth_headers, night, user_id, top, race="NE")
    first = place(client, auth_headers, night, "One#2", 1700, top)
    second = place(client, auth_headers, night, "Three#3", 1700, top)

    play(client, auth_headers, night["id"], human, first)
    payload = play(client, auth_headers, night["id"], elf, second, winner=2)

    assert only(payload, top)["king"]["rows"][0]["entrant_id"] == second
    assert only(payload, top)["played"][0]["throne"] == "moved"


def test_a_king_who_withdraws_through_the_shared_route_frees_the_throne(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    """A crown whose row left reads as an empty throne on every later result."""
    night = open_night(client, auth_headers)
    top = bracket_ids(night)[0]
    king = place(client, auth_headers, night, "Away#1", 1700, top)
    first = place(client, auth_headers, night, "Here#2", 1700, top)
    second = place(client, auth_headers, night, "There#3", 1700, top)
    play(client, auth_headers, night["id"], king, first)

    legacy.withdraw("Away#1")

    assert king_of(board(client, night["id"]), top) is None
    payload = play(client, auth_headers, night["id"], first, second)
    assert only(payload, top)["king"]["rows"][0]["entrant_id"] == first

    back = client.post(
        f"/koth/nights/{night['id']}/entrants/{king}/restore", headers=auth_headers
    )
    assert back.status_code == 200, back.text
    assert only(back.json(), top)["king"]["rows"][0]["entrant_id"] == first


def test_a_king_moved_to_another_bracket_frees_the_throne_he_left(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    """A wearer who stands in another bracket is an empty throne, not a block."""
    night = open_night(client, auth_headers)
    top, second_bracket = bracket_ids(night)[0], bracket_ids(night)[1]
    king = place(client, auth_headers, night, "Moved#1", 1700, top)
    first = place(client, auth_headers, night, "Stays#2", 1700, top)
    third = place(client, auth_headers, night, "Also#3", 1700, top)
    play(client, auth_headers, night["id"], king, first)

    moved = client.put(
        f"/events/{night['id']}/entrants/{king}",
        json={"division_id": second_bracket},
        headers=auth_headers,
    )
    assert moved.status_code == 200, moved.text

    assert king_of(board(client, night["id"]), top) is None
    payload = play(client, auth_headers, night["id"], first, third)
    assert only(payload, top)["king"]["rows"][0]["entrant_id"] == first


def test_a_signup_after_a_result_takes_a_seed_nobody_holds(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    """A result renumbers the line, so the next signup still stands alone at its end."""
    night = open_night(client, auth_headers)
    top = bracket_ids(night)[0]
    first = place(client, auth_headers, night, "Won#1", 1700, top)
    second = place(client, auth_headers, night, "Lost#2", 1700, top)
    play(client, auth_headers, night["id"], first, second)

    late = place(client, auth_headers, night, "Late#3", 1700, top)

    rows = [row for row in entrants(client, night["id"]) if row["division_id"] == top]
    seeds = [row["seed"] for row in rows]
    assert len(seeds) == len(set(seeds)), rows
    assert late in [row["id"] for row in rows]
    queue = only(board(client, night["id"]), top)["queue"]
    assert [row["entrant_id"] for row in queue[-1]["rows"]] == [late]


def set_bounds(
    client: Client, headers: dict[str, str], night: dict[str, Any], values: list[int]
) -> Any:  # noqa: ANN401
    """Name every bracket of the night, strongest first, with its new bound."""
    return client.put(
        f"/koth/nights/{night['id']}/bounds",
        json={
            "bounds": [
                {"division_id": division_id, "lower_bound": bound}
                for division_id, bound in zip(bracket_ids(night), values, strict=True)
            ]
        },
        headers=headers,
    )


def chat(client: Client, night: dict[str, Any], tag: str, mmr: int) -> int:
    """One rated player through the chat door: the cut places him, no admin."""
    enrol(tag, mmr)
    resp = sign_up(client, tag, "streamer", "human")
    assert resp.status_code == 200, resp.text
    return next(
        row["id"]
        for row in entrants(client, night["id"])
        if row["user"]["battleTag"] == tag
    )


def test_a_new_bound_keeps_every_bracket_row_its_crown_and_its_series(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    """The bound moves in place: no bracket is written again, nothing is lost."""
    night = open_night(client, auth_headers)
    top, middle, low = bracket_ids(night)
    first = place(client, auth_headers, night, "Keep#1", 1700, top)
    second = place(client, auth_headers, night, "Keep#2", 1700, top)
    played = play(client, auth_headers, night["id"], first, second)
    crowned = king_of(played, top)
    series_id = only(played, top)["played"][0]["series_id"]

    resp = set_bounds(client, auth_headers, night, [1800, 1500, 0])

    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert [row["division_id"] for row in payload["brackets"]] == [top, middle, low]
    assert [row["name"] for row in payload["brackets"]] == [
        "Bracket 3",
        "Bracket 2",
        "Bracket 1",
    ]
    assert [row["lower_bound"] for row in payload["brackets"]] == [1800, 1500, 0]
    assert king_of(payload, top) == crowned
    assert only(payload, top)["played"][0]["series_id"] == series_id


def test_a_rated_row_falls_to_its_new_bracket_at_the_end_of_the_line(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    """A new bound cuts the rated rows again, exactly as a signup cuts them."""
    night = open_night(client, auth_headers)
    _, middle, low = bracket_ids(night)
    standing = place(client, auth_headers, night, "Stand#1", 1200, low)
    moving = chat(client, night, "Drop#2222", 1500)
    assert [
        row["rows"][0]["entrant_id"]
        for row in only(board(client, night["id"]), middle)["queue"]
    ] == [moving]

    resp = set_bounds(client, auth_headers, night, [1600, 1550, 0])

    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert only(payload, middle)["queue"] == []
    assert [row["rows"][0]["entrant_id"] for row in only(payload, low)["queue"]] == [
        standing,
        moving,
    ]


def test_a_hand_placed_row_and_an_unplaced_row_ignore_a_new_bound(
    client: Client,
    auth_headers: dict[str, str],
    monkeypatch: pytest.MonkeyPatch,
    seeded: dict[str, Any],
) -> None:
    """The cut touches neither a row an admin placed nor a row it never took."""
    silent_w3c(monkeypatch)
    night = open_night(client, auth_headers)
    top, _, low = bracket_ids(night)
    pinned = place(client, auth_headers, night, "Pin#1", 1500, top)
    waiting = client.post(
        f"/events/{night['id']}/entrants/admin",
        json={"user_id": enrol("Wait#2", 1200), "race": "OC"},
        headers=auth_headers,
    )
    assert waiting.status_code == 201, waiting.text

    resp = set_bounds(client, auth_headers, night, [1600, 1550, 0])

    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert [row["rows"][0]["entrant_id"] for row in only(payload, top)["queue"]] == [
        pinned
    ]
    assert only(payload, low)["queue"] == []
    assert [row["entrant_id"] for row in payload["unplaced"]] == [waiting.json()["id"]]


def test_a_king_whose_row_falls_leaves_an_empty_throne(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    """A crown never travels between brackets, so the cut empties the throne."""
    night = open_night(client, auth_headers)
    _, middle, low = bracket_ids(night)
    king = chat(client, night, "Crown#1111", 1500)
    rival = chat(client, night, "Rival#2222", 1500)
    play(client, auth_headers, night["id"], king, rival)
    assert king_of(board(client, night["id"]), middle) is not None

    resp = set_bounds(client, auth_headers, night, [1600, 1550, 0])

    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert king_of(payload, middle) is None
    assert king_of(payload, low) is None
    assert [row["rows"][0]["entrant_id"] for row in only(payload, low)["queue"]] == [
        king,
        rival,
    ]


def test_a_new_bound_holds_the_series_on_the_table_until_it_ends(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    """A row in a running series keeps its bracket; the result then cuts it."""
    night = open_night(client, auth_headers)
    _, middle, low = bracket_ids(night)
    king = chat(client, night, "Busy#1111", 1500)
    rival = chat(client, night, "Busy#2222", 1500)
    free = chat(client, night, "Free#3333", 1500)
    opened = start(client, auth_headers, night["id"], king, rival)
    assert opened.status_code == 201, opened.text
    series_id = _open_id(opened.json(), king)

    resp = set_bounds(client, auth_headers, night, [1600, 1550, 0])

    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert only(payload, middle)["open_series"]["series_id"] == series_id
    assert [row["rows"][0]["entrant_id"] for row in only(payload, low)["queue"]] == [
        free
    ]

    done = client.put(
        f"/koth/nights/{night['id']}/series/{series_id}/result",
        json={"winner": 1},
        headers=auth_headers,
    )

    assert done.status_code == 200, done.text
    payload = done.json()
    assert only(payload, middle)["queue"] == []
    assert king_of(payload, middle) is None
    assert king_of(payload, low) is None
    assert [row["rows"][0]["entrant_id"] for row in only(payload, low)["queue"]] == [
        free,
        king,
        rival,
    ]


def test_a_cancelled_series_frees_its_rows_for_the_new_bound(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    """Taking the series off the table cuts its two rows as the bounds stand."""
    night = open_night(client, auth_headers)
    _, middle, low = bracket_ids(night)
    first = chat(client, night, "Off#1111", 1500)
    second = chat(client, night, "Off#2222", 1500)
    opened = start(client, auth_headers, night["id"], first, second)
    assert opened.status_code == 201, opened.text
    series_id = _open_id(opened.json(), first)
    assert set_bounds(client, auth_headers, night, [1600, 1550, 0]).status_code == 200

    resp = client.delete(
        f"/koth/nights/{night['id']}/series/{series_id}", headers=auth_headers
    )

    assert resp.status_code == 200, resp.text
    payload = resp.json()
    assert only(payload, middle)["queue"] == []
    assert [row["rows"][0]["entrant_id"] for row in only(payload, low)["queue"]] == [
        first,
        second,
    ]


def test_the_bounds_a_night_refuses(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    """The bounds keep the order of the brackets and the weakest opens at 0."""
    night = open_night(client, auth_headers)
    top = bracket_ids(night)[0]
    for values in (
        [1600, 1600, 0],
        [1400, 1500, 0],
        [1600, 1500, 200],
        [1600, 1500, -5],
    ):
        resp = set_bounds(client, auth_headers, night, values)
        assert resp.status_code == 400, f"{values}: {resp.text}"
        assert "error" in resp.json(), resp.text
    one = {"division_id": top, "lower_bound": 1600}
    for body in ({"bounds": [one]}, {"bounds": [one, one, one]}):
        named = client.put(
            f"/koth/nights/{night['id']}/bounds", json=body, headers=auth_headers
        )
        assert named.status_code == 400, named.text

    assert [row["lower_bound"] for row in board(client, night["id"])["brackets"]] == [
        1600,
        1450,
        0,
    ]


def test_a_closed_night_takes_no_new_bound(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    """A night that is over is read only, bounds among everything else."""
    night = open_night(client, auth_headers)
    closed = client.post(f"/koth/nights/{night['id']}/close", headers=auth_headers)
    assert closed.status_code == 200, closed.text

    resp = set_bounds(client, auth_headers, night, [1800, 1500, 0])

    assert resp.status_code == 400, resp.text


def test_a_played_row_names_the_side_that_won(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    """The board says which side won, so a correction needs no series read."""
    night = open_night(client, auth_headers)
    top = bracket_ids(night)[0]
    first = place(client, auth_headers, night, "Side#1", 1700, top)
    second = place(client, auth_headers, night, "Side#2", 1700, top)

    one = play(client, auth_headers, night["id"], first, second)
    two = play(client, auth_headers, night["id"], first, second, winner=2)

    assert only(one, top)["played"][0]["winner_side"] == 1
    assert only(two, top)["played"][0]["winner_side"] == 2
    series_id = only(two, top)["played"][0]["series_id"]
    turned = client.put(
        f"/koth/nights/{night['id']}/series/{series_id}/result",
        json={"winner": 1},
        headers=auth_headers,
    )
    assert turned.status_code == 200, turned.text
    assert only(turned.json(), top)["played"][0]["winner_side"] == 1


def _by_tag(tag: str) -> Any:  # noqa: ANN401
    from sqlmodel import col, select

    return select(User).where(col(User.battleTag) == tag)


def test_game_one_follows_every_score_change(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    """The board, the series route and a clear all keep game 1 on the series score."""
    night = open_night(client, auth_headers)
    top = bracket_ids(night)[0]
    first = place(client, auth_headers, night, "Game#1", 1700, top)
    second = place(client, auth_headers, night, "Game#2", 1700, top)
    played = play(client, auth_headers, night["id"], first, second)
    series_id = only(played, top)["played"][0]["series_id"]

    def game_one() -> str | None:
        with Session() as session:
            game = session.get(DBSeriesGame, (series_id, 1))
            assert game is not None
            return game.winner_side

    assert game_one() == "A"
    turned = client.put(
        f"/series/{series_id}",
        json={"player1_score": 0, "player2_score": 1},
        headers=auth_headers,
    )
    assert turned.status_code == 200, turned.text
    assert game_one() == "B"
    cleared = client.put(
        f"/series/{series_id}?force=true",
        json={"player1_score": None, "player2_score": None},
        headers=auth_headers,
    )
    assert cleared.status_code == 200, cleared.text
    assert game_one() is None
    assert client.get(f"/events/{night['id']}").json()["archived"] is False
