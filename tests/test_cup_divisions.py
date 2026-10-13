"""A cup's divisions are its choice at creation, and its seeds are run per division.

A cup made without divisions refuses every division write and plays one field.
A cup made with them is cut on its run page, refuses its draw while a player
stands in no division, and keeps its divisions once drawn. A cup pins a
player's division and its seed apart, so a new cut keeps the seed pins and a
reshuffle keeps the division pins. A seed write may name one division and
leave every other one as it was.
"""

from typing import Any

from httpx2 import Client

from app.core.db import Session
from app.models.enums import Race
from app.models.event_entrant import EventEntrant
from tests.test_event_divisions import add_player, enter, set_divisions
from tests.test_event_organizers import CUP, Headers
from tests.test_events import add_event


def make_cup(client: Client, headers: Headers, **fields: Any) -> dict[str, Any]:  # noqa: ANN401
    response = client.post("/events", json=CUP | fields, headers=headers)
    assert response.status_code == 201, response.text
    return response.json()


def field_of(event: int, ratings: tuple[int, ...]) -> list[int]:
    """One entrant per rating, strongest last as given."""
    return [
        enter(event, add_player(f"D{event}x{mmr}", {Race.HU: mmr})) for mmr in ratings
    ]


def stage_of(event: dict[str, Any]) -> int:
    return event["stages"][0]["id"]


def seeds_of(client: Client, event: int, headers: Headers) -> dict[int, Any]:
    rows = client.get(f"/events/{event}/entrants", headers=headers).json()
    return {row["id"]: row for row in rows}


def test_a_cup_without_divisions_refuses_every_division_write(
    client: Client, auth_headers: Headers
) -> None:
    cup = make_cup(client, auth_headers)
    assert client.get(f"/events/{cup['id']}").json()["uses_divisions"] is False
    entrant = field_of(cup["id"], (1500,))[0]

    for refused in (
        client.put(
            f"/events/{cup['id']}/divisions", json=[{"name": "A"}], headers=auth_headers
        ),
        client.post(f"/events/{cup['id']}/divisions/assign", headers=auth_headers),
        client.put(
            f"/events/{cup['id']}/entrants/{entrant}/pins",
            json={"division_pinned": True},
            headers=auth_headers,
        ),
    ):
        assert refused.status_code == 400, refused.text
        assert refused.json() == {"error": "This cup plays without divisions"}


def test_a_cup_with_divisions_cuts_and_turns_them_off_before_its_draw(
    client: Client, auth_headers: Headers
) -> None:
    cup = make_cup(client, auth_headers, uses_divisions=True)
    assert client.get(f"/events/{cup['id']}").json()["uses_divisions"] is True
    field_of(cup["id"], (2000, 1900, 1500, 1400))
    set_divisions(
        client,
        cup["id"],
        [{"name": "Top", "lower_bound": 1800}, {"name": "Rest"}],
        auth_headers,
    )
    assigned = client.post(
        f"/events/{cup['id']}/divisions/assign", headers=auth_headers
    )
    assert [row["entrant_count"] for row in assigned.json()["divisions"]] == [2, 2]

    # off takes the divisions back while the cup is not drawn
    off = client.put(
        f"/events/{cup['id']}", json={"uses_divisions": False}, headers=auth_headers
    )
    assert off.status_code == 200, off.text
    read = client.get(f"/events/{cup['id']}").json()
    assert (read["uses_divisions"], read["divisions"]) == (False, [])
    entrants = client.get(f"/events/{cup['id']}/entrants", headers=auth_headers).json()
    assert {row["division_id"] for row in entrants} == {None}


def test_a_cup_draws_no_player_left_outside_its_divisions(
    client: Client, auth_headers: Headers
) -> None:
    cup = make_cup(client, auth_headers, uses_divisions=True)
    field_of(cup["id"], (2000, 1900, 1500, 1400))
    set_divisions(
        client,
        cup["id"],
        [{"name": "Top", "lower_bound": 1800}, {"name": "Rest"}],
        auth_headers,
    )
    client.post(f"/events/{cup['id']}/divisions/assign", headers=auth_headers)
    # a player who signs up after the cut stands in no division yet
    field_of(cup["id"], (1700,))
    drawn = client.post(
        f"/events/{cup['id']}/stages/{stage_of(cup)}/generate", headers=auth_headers
    )
    assert drawn.status_code == 400, drawn.text
    assert drawn.json() == {"error": "Place every player in a division first"}


def test_a_drawn_cup_keeps_its_divisions(client: Client, auth_headers: Headers) -> None:
    cup = make_cup(client, auth_headers, uses_divisions=True)
    field_of(cup["id"], (2000, 1900, 1500, 1400))
    set_divisions(
        client,
        cup["id"],
        [{"name": "Top", "lower_bound": 1800}, {"name": "Rest"}],
        auth_headers,
    )
    client.post(f"/events/{cup['id']}/divisions/assign", headers=auth_headers)
    drawn = client.post(
        f"/events/{cup['id']}/stages/{stage_of(cup)}/generate", headers=auth_headers
    )
    assert drawn.status_code == 200, drawn.text

    for refused in (
        client.put(
            f"/events/{cup['id']}/divisions",
            json=[{"name": "One"}],
            headers=auth_headers,
        ),
        client.post(f"/events/{cup['id']}/divisions/assign", headers=auth_headers),
        client.put(
            f"/events/{cup['id']}", json={"uses_divisions": False}, headers=auth_headers
        ),
    ):
        assert refused.status_code == 409, refused.text


def test_a_seed_write_may_reseed_one_division_alone(
    client: Client, auth_headers: Headers
) -> None:
    cup = make_cup(client, auth_headers, uses_divisions=True)
    top_a, top_b, rest_a, rest_b = field_of(cup["id"], (2000, 1900, 1500, 1400))
    top, rest = (
        band["id"]
        for band in set_divisions(
            client,
            cup["id"],
            [{"name": "Top", "lower_bound": 1800}, {"name": "Rest"}],
            auth_headers,
        )
    )
    client.post(f"/events/{cup['id']}/divisions/assign", headers=auth_headers)
    url = f"/events/{cup['id']}/stages/{stage_of(cup)}/seeds"
    assert (
        client.put(url, json={"source": "mmr"}, headers=auth_headers).status_code == 200
    )

    flipped = client.put(
        url,
        json={"source": "manual", "order": [rest_b, rest_a], "division_id": rest},
        headers=auth_headers,
    )

    assert flipped.status_code == 200, flipped.text
    rows = seeds_of(client, cup["id"], auth_headers)
    assert (rows[rest_b]["seed"], rows[rest_a]["seed"]) == (1, 2)
    # the other division keeps the seeds it had
    assert (rows[top_a]["seed"], rows[top_b]["seed"]) == (1, 2)
    assert rows[top_a]["division_id"] == top


def test_a_cup_keeps_its_division_pin_and_its_seed_pin_apart(
    client: Client, auth_headers: Headers
) -> None:
    cup = make_cup(client, auth_headers, uses_divisions=True)
    strong, _, weak, _ = field_of(cup["id"], (2000, 1900, 1500, 1400))
    _, rest = (
        band["id"]
        for band in set_divisions(
            client,
            cup["id"],
            [{"name": "Top", "lower_bound": 1800}, {"name": "Rest"}],
            auth_headers,
        )
    )
    client.post(f"/events/{cup['id']}/divisions/assign", headers=auth_headers)
    # the strong player is moved down by hand, and that move is a division pin
    moved = client.put(
        f"/events/{cup['id']}/entrants/{strong}",
        json={"division_id": rest},
        headers=auth_headers,
    )
    assert (moved.json()["division_pinned"], moved.json()["seed_pinned"]) == (
        True,
        False,
    )
    with Session.begin() as session:
        session.get_one(EventEntrant, weak).seed = 1
    pinned = client.put(
        f"/events/{cup['id']}/entrants/{weak}/pins",
        json={"seed_pinned": True},
        headers=auth_headers,
    )
    assert pinned.status_code == 200, pinned.text

    # a reshuffle keeps the division pin, and the pinned seed
    url = f"/events/{cup['id']}/stages/{stage_of(cup)}/seeds"
    assert (
        client.put(url, json={"source": "mmr"}, headers=auth_headers).status_code == 200
    )
    rows = seeds_of(client, cup["id"], auth_headers)
    assert rows[strong]["division_pinned"] is True
    assert rows[weak]["seed"] == 1
    # a new cut keeps the seed pin and takes the division pins back
    set_divisions(
        client,
        cup["id"],
        [{"name": "Top", "lower_bound": 1800}, {"name": "Rest"}],
        auth_headers,
    )
    rows = seeds_of(client, cup["id"], auth_headers)
    assert (rows[weak]["seed_pinned"], rows[strong]["division_pinned"]) == (True, False)


def test_only_a_cup_pins_apart_and_hidden_seeds_hide_their_source(
    client: Client, auth_headers: Headers
) -> None:
    signup = add_event(name="Sign-up list")
    entrant = enter(signup, add_player("Lister", {Race.HU: 1500}))
    refused = client.put(
        f"/events/{signup}/entrants/{entrant}/pins",
        json={"seed_pinned": True},
        headers=auth_headers,
    )
    assert refused.status_code == 400
    assert refused.json() == {"error": "Only a cup pins its players"}

    cup = make_cup(client, auth_headers, name="Hidden Cup", hide_seeds=True)
    field_of(cup["id"], (2000, 1900))
    url = f"/events/{cup['id']}/stages/{stage_of(cup)}/seeds"
    assert (
        client.put(url, json={"source": "mmr"}, headers=auth_headers).status_code == 200
    )
    rows = client.get(f"/events/{cup['id']}/entrants").json()
    assert {(row["seed"], row["seed_source"], row["mmr_at_seed"]) for row in rows} == {
        (None, None, None)
    }
