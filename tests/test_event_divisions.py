"""Cutting an event into divisions and seeding the entrants inside them.

The cut reads the MMR of the race an entrant signed up on, so one player with
two rated races lands in a different division on each. An admin moves one
entrant by hand and a later assign leaves it where it was put. Seeds count
1..n inside every division, and a locked stage refuses a further write.
"""

from typing import Any

from httpx2 import Client

from app.core.db import Session
from app.core.divisions import cut
from app.models.enums import EventKind, Race
from app.models.event_entrant import EventEntrant
from app.models.event_stage import EventStage
from app.models.user import User
from app.models.w3c_stats import W3CStats
from tests.test_events import add_event


def add_player(name: str, ratings: dict[Race, int]) -> int:
    """One player with a W3C rating on each race the map names."""
    with Session.begin() as session:
        user = User(
            name=name,
            battleTag=f"{name}#1000",
            discordTag="",
            discordId="",
            race=next(iter(ratings), Race.HU),
        )
        session.add(user)
        session.flush()
        assert user.id is not None
        session.add_all(
            W3CStats(user_id=user.id, race=race, wc3_season=22, games=100, mmr=mmr)
            for race, mmr in ratings.items()
        )
        return user.id


def enter(event_id: int, user_id: int, race: Race = Race.HU) -> int:
    with Session.begin() as session:
        row = EventEntrant(event_id=event_id, user_id=user_id, race=race)
        session.add(row)
        session.flush()
        assert row.id is not None
        return row.id


def add_stage(event_id: int) -> int:
    with Session.begin() as session:
        stage = EventStage(event_id=event_id, position=1)
        session.add(stage)
        session.flush()
        assert stage.id is not None
        return stage.id


def divisions(client: Client, event_id: int) -> list[dict[str, Any]]:
    return client.get(f"/events/{event_id}").json()["divisions"]


def set_divisions(
    client: Client, event_id: int, body: list[dict[str, Any]], headers: dict[str, str]
) -> list[dict[str, Any]]:
    response = client.put(f"/events/{event_id}/divisions", json=body, headers=headers)
    assert response.status_code == 200, response.text
    return response.json()["divisions"]


def test_the_cut_reads_a_lower_bound_and_a_size(client: Client) -> None:
    """Two ways to name the same three bands, over the same pool.

    Bands come strongest first. A rating that reaches no bound, and an entrant
    with no rating at all, sit in the weakest band.
    """
    pool = [(1, 2200), (2, 1900), (3, 1500), (4, 1200), (5, None)]

    by_bound = cut(pool, [(2000, None), (1400, None), (None, None)])

    assert by_bound == {1: 0, 2: 1, 3: 1, 4: 2, 5: 2}
    by_size = cut(pool, [(None, 1), (None, 2), (None, 1)])
    # The last band takes what is left, so the unrated entrant lands there
    assert by_size == {1: 0, 2: 1, 3: 1, 4: 2, 5: 2}


def test_an_assign_cuts_by_bound_and_reads_the_signup_race(
    client: Client, auth_headers: dict[str, str]
) -> None:
    """One player rated 2100 on Human and 1300 on Orc enters on Orc, so the
    cut puts them in the lower division and never in the Human one."""
    event = add_event(kind=EventKind.cup)
    two_race = add_player("Switcher", {Race.HU: 2100, Race.OC: 1300})
    strong = add_player("Strong", {Race.HU: 2050})
    enter(event, two_race, Race.OC)
    enter(event, strong, Race.HU)
    bands = set_divisions(
        client,
        event,
        [{"name": "Pro", "lower_bound": 2000}, {"name": "Open"}],
        auth_headers,
    )
    assert [band["entrant_count"] for band in bands] == [0, 0]

    assigned = client.post(f"/events/{event}/divisions/assign", headers=auth_headers)

    assert assigned.status_code == 200, assigned.text
    counts = {
        band["name"]: band["entrant_count"] for band in assigned.json()["divisions"]
    }
    assert counts == {"Pro": 1, "Open": 1}
    rows = {
        row["user"]["name"]: row
        for row in client.get(f"/events/{event}/entrants").json()
    }
    assert rows["Switcher"]["division_id"] == bands[1]["id"]
    assert rows["Strong"]["division_id"] == bands[0]["id"]


def test_an_assign_cuts_by_size_and_leaves_a_hand_placed_entrant(
    client: Client, auth_headers: dict[str, str]
) -> None:
    """A move marks the entrant placed by hand, and the next assign skips it."""
    event = add_event(kind=EventKind.cup)
    entrants = [
        enter(event, add_player(f"P{mmr}", {Race.HU: mmr}))
        for mmr in (2200, 2000, 1800, 1600)
    ]
    bands = set_divisions(
        client, event, [{"name": "Top", "size": 2}, {"name": "Rest"}], auth_headers
    )
    first = client.post(f"/events/{event}/divisions/assign", headers=auth_headers)
    assert first.status_code == 200, first.text

    moved = client.put(
        f"/events/{event}/entrants/{entrants[0]}",
        json={"division_id": bands[1]["id"]},
        headers=auth_headers,
    )

    assert moved.status_code == 200, moved.text
    assert moved.json()["manual_placement"] is True
    again = client.post(f"/events/{event}/divisions/assign", headers=auth_headers)
    counts = {band["name"]: band["entrant_count"] for band in again.json()["divisions"]}
    # The strongest entrant stays where the admin put it, so Top takes the next two
    assert counts == {"Top": 2, "Rest": 2}
    rows = {row["id"]: row for row in client.get(f"/events/{event}/entrants").json()}
    assert rows[entrants[0]]["division_id"] == bands[1]["id"]
    unknown = client.put(
        f"/events/{event}/entrants/{entrants[1]}",
        json={"division_id": 404},
        headers=auth_headers,
    )
    assert unknown.status_code == 400
    assert unknown.json() == {"error": "Division not found by id: 404"}

    # New bands drop the old placement, so the assign takes the entrant back
    fresh = set_divisions(
        client, event, [{"name": "Top", "size": 2}, {"name": "Rest"}], auth_headers
    )
    client.post(f"/events/{event}/divisions/assign", headers=auth_headers)
    rows = {row["id"]: row for row in client.get(f"/events/{event}/entrants").json()}
    assert rows[entrants[0]]["division_id"] == fresh[0]["id"]
    assert rows[entrants[0]]["manual_placement"] is False


def test_the_seeds_count_from_one_inside_each_division(
    client: Client, auth_headers: dict[str, str]
) -> None:
    """Four entrants, two divisions, so the seeds read 1, 2, 1, 2."""
    event = add_event(kind=EventKind.cup)
    stage = add_stage(event)
    for mmr in (2200, 2000, 1800, 1600):
        enter(event, add_player(f"P{mmr}", {Race.HU: mmr}))
    set_divisions(
        client, event, [{"name": "Top", "size": 2}, {"name": "Rest"}], auth_headers
    )
    client.post(f"/events/{event}/divisions/assign", headers=auth_headers)

    seeded = client.put(
        f"/events/{event}/stages/{stage}/seeds",
        json={"source": "mmr"},
        headers=auth_headers,
    )

    assert seeded.status_code == 200, seeded.text
    rows = seeded.json()
    assert [row["seed"] for row in rows] == [1, 2, 1, 2]
    assert [row["user"]["name"] for row in rows] == ["P2200", "P2000", "P1800", "P1600"]
    assert [row["mmr_at_seed"] for row in rows] == [2200, 2000, 1800, 1600]
    assert {row["seed_source"] for row in rows} == {"mmr"}


def test_a_manual_order_seeds_and_the_engine_sources_refuse(
    client: Client, auth_headers: dict[str, str]
) -> None:
    """Manual takes the list; the two sources that read standings answer not_built."""
    event = add_event(kind=EventKind.cup)
    stage = add_stage(event)
    entrants = [
        enter(event, add_player(f"P{mmr}", {Race.HU: mmr})) for mmr in (2200, 1600)
    ]

    seeded = client.put(
        f"/events/{event}/stages/{stage}/seeds",
        json={"source": "manual", "order": [entrants[1], entrants[0]]},
        headers=auth_headers,
    )

    assert seeded.status_code == 200, seeded.text
    assert [row["id"] for row in seeded.json()] == [entrants[1], entrants[0]]
    assert [row["seed"] for row in seeded.json()] == [1, 2]
    nothing = client.put(
        f"/events/{event}/stages/{stage}/seeds",
        json={"source": "manual"},
        headers=auth_headers,
    )
    assert nothing.json() == {"error": "Manual seeding takes an order of entrant ids"}
    stranger = client.put(
        f"/events/{event}/stages/{stage}/seeds",
        json={"source": "manual", "order": [404]},
        headers=auth_headers,
    )
    assert stranger.json() == {"error": "Not an entrant of this event: 404"}
    later = client.put(
        f"/events/{event}/stages/{stage}/seeds",
        json={"source": "previous_stage"},
        headers=auth_headers,
    )
    assert later.status_code == 400
    assert later.json()["error"] == "not_built"
    # Random and invitation reseed the same pool and stamp their own source
    for source in ("random", "invitation"):
        rows = client.put(
            f"/events/{event}/stages/{stage}/seeds",
            json={"source": source},
            headers=auth_headers,
        ).json()
        assert sorted(row["seed"] for row in rows) == [1, 2]
        assert {row["seed_source"] for row in rows} == {source}


def test_a_locked_stage_refuses_a_further_seed_write(
    client: Client, auth_headers: dict[str, str]
) -> None:
    event = add_event(kind=EventKind.cup)
    stage = add_stage(event)
    enter(event, add_player("Only", {Race.HU: 1700}))
    first = client.put(
        f"/events/{event}/stages/{stage}/seeds",
        json={"source": "mmr"},
        headers=auth_headers,
    )
    assert first.status_code == 200, first.text

    locked = client.post(
        f"/events/{event}/stages/{stage}/seeds/lock", headers=auth_headers
    )

    assert locked.status_code == 200, locked.text
    assert locked.json()["seeds_locked_at"] is not None
    refused = client.put(
        f"/events/{event}/stages/{stage}/seeds",
        json={"source": "mmr"},
        headers=auth_headers,
    )
    assert refused.status_code == 400
    assert refused.json() == {"error": "The seeds of this stage are locked"}
    assert client.post(
        f"/events/{event}/stages/404/seeds/lock", headers=auth_headers
    ).json() == {"error": "Stage not found by id: 404"}


def test_every_division_and_seed_write_asks_for_an_admin(client: Client) -> None:
    event = add_event(kind=EventKind.cup)
    stage = add_stage(event)

    assert client.put(f"/events/{event}/divisions", json=[]).status_code == 401
    assert client.post(f"/events/{event}/divisions/assign").status_code == 401
    assert client.put(f"/events/{event}/entrants/1", json={}).status_code == 401
    assert (
        client.put(
            f"/events/{event}/stages/{stage}/seeds", json={"source": "mmr"}
        ).status_code
        == 401
    )
    assert client.post(f"/events/{event}/stages/{stage}/seeds/lock").status_code == 401


def test_an_assign_with_no_divisions_refuses(
    client: Client, auth_headers: dict[str, str]
) -> None:
    event = add_event(kind=EventKind.cup)

    refused = client.post(f"/events/{event}/divisions/assign", headers=auth_headers)

    assert refused.status_code == 400
    assert refused.json() == {"error": "The event has no divisions to assign"}
