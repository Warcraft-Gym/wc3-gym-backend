"""The board names the crowned row, and the shared event writes leave a KOTH night alone.

A night cuts its own brackets, orders its own line and removes its own rows, so
the shared cut, seed, division and delete writes refuse it, and a closed night
refuses a placement. The same writes still run on an event of any other kind.
"""

from typing import Any

import pytest
from httpx2 import Client

from app.core.db import Session
from app.models.enums import EventKind, Race
from app.models.event_entrant import EventEntrant
from app.models.season import Season
from app.models.types import utcnow
from tests.test_event_divisions import add_player, add_stage, enter, set_divisions
from tests.test_events import add_event
from tests.test_koth_guards import close, crown
from tests.test_koth_live import (
    board,
    bracket_ids,
    chat,
    only,
    place,
    place_user,
    play,
)
from tests.test_koth_moves import stored_king, two_races
from tests.test_koth_night import entrants, open_night

# Every signup asks W3Champions, so each test here answers for it
pytestmark = pytest.mark.usefixtures("quiet_w3c")


def test_the_board_names_the_crowned_race_row_and_follows_the_crown(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    """A king on two races in one bracket wears the crown on one row; the board names it."""
    night = open_night(client, auth_headers)
    top = bracket_ids(night)[0]
    user_id = two_races("Duo#7001", 1700)
    human = place_user(client, auth_headers, night, user_id, top)
    elf = place_user(client, auth_headers, night, user_id, top, race="NE")
    beaten = place(client, auth_headers, night, "Beat#7002", 1700, top)

    played = play(client, auth_headers, night["id"], elf, beaten)

    assert only(played, top)["king_entrant_id"] == elf
    crown(client, auth_headers, night["id"], top, human)
    assert only(board(client, night["id"]), top)["king_entrant_id"] == human


@pytest.mark.parametrize("where", ["withdrawn", "another bracket"])
def test_a_crown_on_a_row_that_left_or_stands_elsewhere_names_no_row(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any], where: str
) -> None:
    """The stored crown counts only while it names a live row of its own bracket."""
    night = open_night(client, auth_headers)
    top, middle, _ = bracket_ids(night)
    king = place(client, auth_headers, night, "King#7101", 1700, top)
    beaten = place(client, auth_headers, night, "Beat#7102", 1700, top)
    play(client, auth_headers, night["id"], king, beaten)
    # No route leaves a crown on such a row, so the row changes under it directly
    with Session.begin() as session:
        row = session.get(EventEntrant, king)
        assert row is not None
        if where == "withdrawn":
            row.withdrawn_at = utcnow()
        else:
            row.division_id = middle

    bracket = only(board(client, night["id"]), top)

    assert stored_king(top) == king
    assert (bracket["king"], bracket["king_entrant_id"]) == (None, None)


def test_the_shared_assign_refuses_a_koth_night(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    """The shared cut reads today's rating, so it would undo the frozen brackets."""
    night = open_night(client, auth_headers)

    resp = client.post(f"/events/{night['id']}/divisions/assign", headers=auth_headers)

    assert resp.status_code == 400, resp.text
    assert resp.json()["error"] == "A KOTH event cuts its own brackets"


def test_the_shared_seed_write_refuses_a_koth_night(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    """A seed write would renumber the line and overwrite the stored cut rating."""
    night = open_night(client, auth_headers)
    row = chat(client, night, "Seat#7201", 1500)
    before = next(one for one in entrants(client, night["id"]) if one["id"] == row)

    resp = client.put(
        f"/events/{night['id']}/stages/{night['stages'][0]['id']}/seeds",
        json={"source": "random"},
        headers=auth_headers,
    )

    assert resp.status_code == 400, resp.text
    assert resp.json()["error"] == "A KOTH event orders its line on its run page"
    after = next(one for one in entrants(client, night["id"]) if one["id"] == row)
    assert (after["seed"], after["mmr_at_seed"]) == (before["seed"], 1500)


def test_the_shared_division_write_refuses_a_koth_night(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    """Replacing the divisions would drop every placement and crown of the night."""
    night = open_night(client, auth_headers)

    resp = client.put(
        f"/events/{night['id']}/divisions",
        json=[{"name": "One", "lower_bound": 0}],
        headers=auth_headers,
    )

    assert resp.status_code == 400, resp.text
    assert (
        resp.json()["error"] == "A KOTH event moves its brackets through their bounds"
    )
    assert [
        row["division_id"] for row in board(client, night["id"])["brackets"]
    ] == bracket_ids(night)


def test_the_shared_delete_refuses_an_open_koth_night(
    client: Client, auth_headers: dict[str, str], seeded: dict[str, Any]
) -> None:
    """The shared delete skips the forfeit rule, so a night removes a row on its run page."""
    night = open_night(client, auth_headers)
    _, middle, _ = bracket_ids(night)
    row = chat(client, night, "Seat#7401", 1500)

    resp = client.delete(f"/events/{night['id']}/entrants/{row}", headers=auth_headers)

    assert resp.status_code == 400, resp.text
    assert resp.json()["error"] == "A KOTH event removes a player on its run page"
    rows = {one["id"]: one for one in entrants(client, night["id"])}
    assert (rows[row]["division_id"], rows[row]["withdrawn_at"]) == (middle, None)


@pytest.mark.parametrize(
    ("write", "refusal"),
    [
        ("place", "The event is closed"),
        ("remove", "A KOTH event removes a player on its run page"),
    ],
)
def test_a_closed_night_refuses_a_shared_placement_and_removal(
    client: Client,
    auth_headers: dict[str, str],
    seeded: dict[str, Any],
    write: str,
    refusal: str,
) -> None:
    """A closed night keeps its rows where the close left them."""
    night = open_night(client, auth_headers)
    _, middle, low = bracket_ids(night)
    row = chat(client, night, "Seat#7301", 1500)
    close(client, auth_headers, night["id"])

    if write == "place":
        resp = client.put(
            f"/events/{night['id']}/entrants/{row}",
            json={"division_id": low},
            headers=auth_headers,
        )
    else:
        resp = client.delete(
            f"/events/{night['id']}/entrants/{row}", headers=auth_headers
        )

    assert resp.status_code == 400, resp.text
    assert resp.json()["error"] == refusal
    rows = {one["id"]: one for one in entrants(client, night["id"])}
    assert rows[row]["division_id"] == middle


def test_the_guarded_writes_still_run_on_an_event_of_another_kind(
    client: Client, auth_headers: dict[str, str]
) -> None:
    """Only a KOTH night is refused; a cup divides, cuts, seeds, places and removes."""
    event = add_event(kind=EventKind.cup)
    stage = add_stage(event)
    first = enter(event, add_player("Cup1", {Race.HU: 1800}))
    second = enter(event, add_player("Cup2", {Race.HU: 1600}))
    divisions = set_divisions(
        client,
        event,
        [{"name": "Top", "lower_bound": 1700}, {"name": "Rest", "lower_bound": 0}],
        auth_headers,
    )
    assigned = client.post(f"/events/{event}/divisions/assign", headers=auth_headers)
    assert assigned.status_code == 200, assigned.text
    seeded = client.put(
        f"/events/{event}/stages/{stage}/seeds",
        json={"source": "mmr"},
        headers=auth_headers,
    )
    assert seeded.status_code == 200, seeded.text
    # A closed event of another kind still takes a placement and a removal
    with Session.begin() as session:
        row = session.get(Season, event)
        assert row is not None
        row.closed_at = utcnow()

    placed = client.put(
        f"/events/{event}/entrants/{second}",
        json={"division_id": divisions[0]["id"]},
        headers=auth_headers,
    )
    removed = client.delete(f"/events/{event}/entrants/{first}", headers=auth_headers)

    assert placed.status_code == 200, placed.text
    assert placed.json()["division_id"] == divisions[0]["id"]
    assert removed.status_code == 204, removed.text
