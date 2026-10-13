"""The draw seeds a cup by its stage's seed source, and the seeds lock with it.

An mmr stage seeds the unseeded by the newest rating, the unrated last; a
random stage shuffles them; a manual stage waits until every entrant has a
seed. A reseed keeps a seed placed by hand. The draw locks the seeds, and the
unlock waits until the draw is taken back. An event may hide its seed numbers
from every reader who does not run it.
"""

from typing import Any

import pytest
from httpx2 import Client
from sqlmodel import col, select

from app.core.db import Session
from app.models.enums import EventKind, Race, StageFormat
from app.models.event_entrant import EventEntrant
from app.models.event_stage import EventStage
from tests.test_event_divisions import add_player, divided_cup, enter
from tests.test_event_organizers import Headers, Member, create, grant
from tests.test_events import add_event
from tests.test_stage_engine import bracket, cup, players_of, score

STAGES = [{"format": "single_elimination", "best_of": 1}]


def single_stage(event: int) -> int:
    """The first stage of the event, a single elimination bracket."""
    with Session.begin() as session:
        stage = EventStage(
            event_id=event, position=1, format=StageFormat.single_elimination
        )
        session.add(stage)
        session.flush()
        assert stage.id is not None
        return stage.id


def seeds(event: int) -> dict[int, tuple[int | None, str | None, int | None]]:
    """Each entrant id against its seed, the source that cut it and its MMR then."""
    with Session.begin() as session:
        return {
            row.id: (row.seed, row.seed_source, row.mmr_at_seed)
            for row in session.scalars(
                select(EventEntrant).where(col(EventEntrant.event_id) == event)
            )
            if row.id is not None
        }


def user_of(entrant_id: int) -> int | None:
    with Session.begin() as session:
        return session.get_one(EventEntrant, entrant_id).user_id


def first_pair(stage: int) -> set[int | None]:
    """The two players of the first series of round 1."""
    return set(bracket(stage)[0]["sides"])


def stage_of(client: Client, event: int, stage: int) -> dict[str, Any]:
    stages = client.get(f"/events/{event}").json()["stages"]
    return next(row for row in stages if row["id"] == stage)


def put_seeds(
    client: Client,
    headers: Headers,
    event: int,
    stage: int,
    **body: Any,  # noqa: ANN401
) -> Any:  # noqa: ANN401
    return client.put(
        f"/events/{event}/stages/{stage}/seeds", json=body, headers=headers
    )


def test_a_draw_on_an_mmr_stage_seeds_the_field_strongest_first_unrated_last(
    client: Client, auth_headers: Headers
) -> None:
    event = add_event(kind=EventKind.cup)
    stage = single_stage(event)
    unrated = enter(event, add_player("Unrated", {}))
    weak, middle, strong = (
        enter(event, add_player(f"P{mmr}", {Race.HU: mmr}))
        for mmr in (1500, 1600, 1700)
    )

    drawn = client.post(
        f"/events/{event}/stages/{stage}/generate", headers=auth_headers
    )

    assert drawn.status_code == 200, drawn.text
    assert seeds(event) == {
        strong: (1, "mmr", 1700),
        middle: (2, "mmr", 1600),
        weak: (3, "mmr", 1500),
        unrated: (4, "mmr", None),
    }
    assert first_pair(stage) == {user_of(strong), user_of(unrated)}


def test_the_first_round_of_a_swiss_stage_seeds_by_mmr_and_locks(
    client: Client, auth_headers: Headers
) -> None:
    event = add_event(kind=EventKind.cup)
    single_stage(event)
    written = client.put(
        f"/events/{event}/stages",
        json=[{"format": "swiss", "swiss_rounds": 2}],
        headers=auth_headers,
    )
    stage = written.json()["stages"][0]["id"]
    weak, strong = (
        enter(event, add_player(f"P{mmr}", {Race.HU: mmr})) for mmr in (1500, 1700)
    )

    drawn = client.post(f"/events/{event}/stages/{stage}/rounds", headers=auth_headers)

    assert drawn.status_code == 200, drawn.text
    assert seeds(event) == {strong: (1, "mmr", 1700), weak: (2, "mmr", 1500)}
    assert stage_of(client, event, stage)["seeds_locked_at"] is not None
    reseed = put_seeds(client, auth_headers, event, stage, source="mmr")
    assert reseed.status_code == 409


def test_a_draw_fills_only_the_unseeded_around_the_seeds_already_written(
    client: Client, auth_headers: Headers
) -> None:
    event = add_event(kind=EventKind.cup)
    stage = single_stage(event)
    early = [
        enter(event, add_player(f"P{mmr}", {Race.HU: mmr}))
        for mmr in (1500, 1600, 1700)
    ]
    written = put_seeds(
        client, auth_headers, event, stage, source="manual", order=early
    )
    assert written.status_code == 200, written.text
    late = enter(event, add_player("Late", {Race.HU: 2000}))

    drawn = client.post(
        f"/events/{event}/stages/{stage}/generate", headers=auth_headers
    )

    assert drawn.status_code == 200, drawn.text
    assert drawn.json() == {"series": 3, "rounds": 2}
    after = seeds(event)
    assert [after[entrant][0] for entrant in early] == [1, 2, 3]
    assert after[late] == (4, "mmr", 2000)
    assert first_pair(stage) == {user_of(early[0]), user_of(late)}


def test_a_draw_on_a_random_stage_shuffles(
    client: Client, auth_headers: Headers, monkeypatch: pytest.MonkeyPatch
) -> None:
    event = add_event(kind=EventKind.cup)
    single_stage(event)
    written = client.put(
        f"/events/{event}/stages",
        json=[STAGES[0] | {"seed_source": "random"}],
        headers=auth_headers,
    )
    assert written.status_code == 200, written.text
    stage = written.json()["stages"][0]["id"]
    assert written.json()["stages"][0]["seed_source"] == "random"
    # Signed up strongest first, so neither MMR nor signup order reads reversed
    entrants = [
        enter(event, add_player(f"P{mmr}", {Race.HU: mmr}))
        for mmr in (2000, 1900, 1800, 1700)
    ]
    monkeypatch.setattr("app.services.events.random.shuffle", list.reverse)

    drawn = client.post(
        f"/events/{event}/stages/{stage}/generate", headers=auth_headers
    )

    assert drawn.status_code == 200, drawn.text
    after = seeds(event)
    assert [after[entrant][:2] for entrant in reversed(entrants)] == [
        (1, "random"),
        (2, "random"),
        (3, "random"),
        (4, "random"),
    ]


def test_a_draw_on_a_manual_stage_refuses_until_every_entrant_has_a_seed(
    client: Client, auth_headers: Headers
) -> None:
    event = add_event(kind=EventKind.cup)
    single_stage(event)
    written = client.put(
        f"/events/{event}/stages",
        json=[STAGES[0] | {"seed_source": "manual"}],
        headers=auth_headers,
    )
    stage = written.json()["stages"][0]["id"]
    entrants = [
        enter(event, add_player(f"P{mmr}", {Race.HU: mmr}))
        for mmr in (2000, 1900, 1800, 1700)
    ]

    refused = client.post(
        f"/events/{event}/stages/{stage}/generate", headers=auth_headers
    )

    assert refused.status_code == 409
    assert refused.json() == {"error": "Seed every entrant first"}
    assert bracket(stage) == []
    assert stage_of(client, event, stage)["seeds_locked_at"] is None
    assert {seed for seed, _, _ in seeds(event).values()} == {None}
    order = [entrants[2], entrants[0], entrants[3], entrants[1]]
    written = put_seeds(
        client, auth_headers, event, stage, source="manual", order=order
    )
    assert written.status_code == 200, written.text
    drawn = client.post(
        f"/events/{event}/stages/{stage}/generate", headers=auth_headers
    )
    assert drawn.status_code == 200, drawn.text
    assert first_pair(stage) == {user_of(order[0]), user_of(order[3])}


@pytest.mark.parametrize(
    ("stage_body", "draw"),
    [(STAGES[0], "generate"), ({"format": "swiss", "swiss_rounds": 2}, "rounds")],
)
def test_a_refused_draw_writes_no_seed(
    client: Client, auth_headers: Headers, stage_body: dict[str, Any], draw: str
) -> None:
    event = add_event(kind=EventKind.cup)
    single_stage(event)
    written = client.put(
        f"/events/{event}/stages", json=[stage_body], headers=auth_headers
    )
    assert written.status_code == 200, written.text
    stage = written.json()["stages"][0]["id"]
    held = client.put(f"/events/{event}", json={"entrant_min": 4}, headers=auth_headers)
    assert held.status_code == 200, held.text
    early = [
        enter(event, add_player(f"P{mmr}", {Race.HU: mmr}))
        for mmr in (1500, 1600, 1700)
    ]

    refused = client.post(
        f"/events/{event}/stages/{stage}/{draw}", headers=auth_headers
    )

    assert refused.status_code == 400
    assert "at least 4" in refused.json()["error"]
    assert {seed for seed, _, _ in seeds(event).values()} == {None}
    assert stage_of(client, event, stage)["seeds_locked_at"] is None
    late = enter(event, add_player("Late", {Race.HU: 2000}))
    drawn = client.post(f"/events/{event}/stages/{stage}/{draw}", headers=auth_headers)
    assert drawn.status_code == 200, drawn.text
    after = seeds(event)
    assert after[late] == (1, "mmr", 2000)
    assert [after[entrant][0] for entrant in reversed(early)] == [2, 3, 4]


def test_a_later_stage_draws_only_the_entrants_advance_seeded(
    client: Client, auth_headers: Headers
) -> None:
    event, (first, second) = cup(
        4, StageFormat.round_robin, stages=2, advance_count=2, points_series_won=3
    )
    top = players_of(event)[0]
    drawn = client.post(
        f"/events/{event}/stages/{first}/generate", headers=auth_headers
    )
    assert drawn.status_code == 200, drawn.text
    for row in bracket(first):
        won = row["sides"][0] == top or row["sides"][1] != top
        score(client, auth_headers, row["id"], 2 if won else 0, 0 if won else 2)
    moved = client.post(f"/events/{event}/stages/{first}/advance", headers=auth_headers)
    assert moved.status_code == 200, moved.text

    later = client.post(
        f"/events/{event}/stages/{second}/generate", headers=auth_headers
    )

    assert later.status_code == 200, later.text
    out = {
        user_of(entrant) for entrant, (seed, _, _) in seeds(event).items() if not seed
    }
    assert len(out) == 2
    assert not out & {side for row in bracket(second) for side in row["sides"]}


def test_a_reseed_keeps_the_hand_placed_seeds_and_fills_around_them(
    client: Client, auth_headers: Headers
) -> None:
    event = add_event(kind=EventKind.cup)
    stage = single_stage(event)
    weakest, *rest = (
        enter(event, add_player(f"P{mmr}", {Race.HU: mmr}))
        for mmr in (1500, 1600, 1700, 1800)
    )
    with Session.begin() as session:
        row = session.get_one(EventEntrant, weakest)
        row.seed = 1
    # a cup pins the seed apart from the division
    pinned = client.put(
        f"/events/{event}/entrants/{weakest}/pins",
        json={"seed_pinned": True},
        headers=auth_headers,
    )
    assert pinned.status_code == 200, pinned.text
    assert pinned.json()["seed_pinned"] is True

    written = put_seeds(client, auth_headers, event, stage, source="mmr")

    assert written.status_code == 200, written.text
    after = seeds(event)
    assert after[weakest][0] == 1
    assert [after[entrant][0] for entrant in reversed(rest)] == [2, 3, 4]


def test_a_previous_stage_reseed_does_not_keep_a_pinned_entrant_that_went_out(
    client: Client, auth_headers: Headers
) -> None:
    event, (first, second) = cup(
        4, StageFormat.round_robin, stages=2, advance_count=2, points_series_won=3
    )
    top = players_of(event)[0]
    drawn = client.post(
        f"/events/{event}/stages/{first}/generate", headers=auth_headers
    )
    assert drawn.status_code == 200, drawn.text
    for row in bracket(first):
        won = row["sides"][0] == top or row["sides"][1] != top
        score(client, auth_headers, row["id"], 2 if won else 0, 0 if won else 2)
    table = client.get(f"/events/{event}/stages/{first}/standings").json()
    last = table[0]["rows"][-1]["entrant_id"]
    with Session.begin() as session:
        row = session.get_one(EventEntrant, last)
        row.manual_placement = True
        assert row.seed is not None

    written = put_seeds(client, auth_headers, event, second, source="previous_stage")

    assert written.status_code == 200, written.text
    after = seeds(event)
    assert after[last][0] is None
    assert sorted(seed for seed, _, _ in after.values() if seed) == [1, 2]


def test_the_draw_locks_the_seeds_and_unlock_waits_for_the_redraw(
    client: Client, auth_headers: Headers
) -> None:
    event = divided_cup()
    stage = single_stage(event)
    response = client.put(
        f"/events/{event}/divisions",
        json=[{"name": "Top"}, {"name": "Rest"}],
        headers=auth_headers,
    )
    top, rest = (row["id"] for row in response.json()["divisions"])
    entrants = [
        enter(event, add_player(f"P{mmr}", {Race.HU: mmr}))
        for mmr in (2000, 1900, 1800, 1700)
    ]
    with Session.begin() as session:
        for index, entrant in enumerate(entrants):
            session.get_one(EventEntrant, entrant).division_id = (
                top if index < 2 else rest
            )
    lock = f"/events/{event}/stages/{stage}/seeds/lock"

    drawn = client.post(
        f"/events/{event}/stages/{stage}/generate", headers=auth_headers
    )

    assert drawn.status_code == 200, drawn.text
    assert stage_of(client, event, stage)["seeds_locked_at"] is not None
    reseed = put_seeds(client, auth_headers, event, stage, source="mmr")
    assert reseed.status_code == 409
    assert reseed.json() == {"error": "The seeds of this stage are locked"}
    move = client.put(
        f"/events/{event}/entrants/{entrants[0]}",
        json={"division_id": rest},
        headers=auth_headers,
    )
    assert move.status_code == 409
    assert move.json() == {"error": "The seeds of this event are locked"}
    unlock = client.delete(lock, headers=auth_headers)
    assert unlock.status_code == 409
    assert unlock.json() == {
        "error": "The stage holds series; take its draw back first"
    }
    assert stage_of(client, event, stage)["seeds_locked_at"] is not None
    undone = client.delete(
        f"/events/{event}/stages/{stage}/series", headers=auth_headers
    )
    assert undone.status_code == 200, undone.text
    assert stage_of(client, event, stage)["seeds_locked_at"] is None
    reseed = put_seeds(client, auth_headers, event, stage, source="mmr")
    assert reseed.status_code == 200, reseed.text


def test_a_hand_lock_unlocks_and_the_reseed_opens_again(
    client: Client, auth_headers: Headers, member: Member
) -> None:
    event = add_event(kind=EventKind.cup)
    stage = single_stage(event)
    enter(event, add_player("Only", {Race.HU: 1700}))
    lock = f"/events/{event}/stages/{stage}/seeds/lock"
    assert client.post(lock, headers=auth_headers).status_code == 200
    reseed = put_seeds(client, auth_headers, event, stage, source="mmr")
    assert reseed.status_code == 409

    assert client.delete(lock, headers=member("60")).status_code == 403
    unlocked = client.delete(lock, headers=auth_headers)

    assert unlocked.status_code == 200, unlocked.text
    assert unlocked.json()["seeds_locked_at"] is None
    assert unlocked.json()["id"] == stage
    reseed = put_seeds(client, auth_headers, event, stage, source="mmr")
    assert reseed.status_code == 200, reseed.text


def hidden_cup(
    client: Client, admin: Headers, member: Member
) -> tuple[int, int, Headers, list[int]]:
    """A cup an organizer runs that hides its seeds, seeded by MMR.

    The players sign up weakest first, so the seed order and the signup
    order read reversed.
    """
    grant(client, admin, "50")
    organizer = member("50")
    event = create(client, organizer, stages=STAGES, hide_seeds=True)
    assert event["hide_seeds"] is True
    stage = event["stages"][0]["id"]
    entrants = [
        enter(event["id"], add_player(f"P{mmr}", {Race.HU: mmr}))
        for mmr in (1500, 1600, 1700, 1800)
    ]
    written = put_seeds(client, organizer, event["id"], stage, source="mmr")
    assert written.status_code == 200, written.text
    return event["id"], stage, organizer, entrants


def test_hidden_seeds_read_only_for_the_events_runners_on_the_entrants_read(
    client: Client, auth_headers: Headers, member: Member
) -> None:
    event, _, organizer, entrants = hidden_cup(client, auth_headers, member)
    path = f"/events/{event}/entrants"

    anonymous = client.get(path)

    assert anonymous.status_code == 200, anonymous.text
    assert [row["id"] for row in anonymous.json()] == entrants
    assert [row["seed"] for row in anonymous.json()] == [None] * 4
    assert anonymous.headers["Cache-Control"].startswith("public")
    other = client.get(path, headers=member("51"))
    assert [row["seed"] for row in other.json()] == [None] * 4
    assert not other.headers.get("Cache-Control", "").startswith("public")
    for headers in (organizer, auth_headers):
        rows = client.get(path, headers=headers).json()
        assert [row["id"] for row in rows] == entrants[::-1]
        assert [row["seed"] for row in rows] == [1, 2, 3, 4]
    shown = client.put(
        f"/events/{event}", json={"hide_seeds": False}, headers=organizer
    )
    assert shown.status_code == 200, shown.text
    assert [row["seed"] for row in client.get(path).json()] == [1, 2, 3, 4]


def test_hidden_seeds_read_only_for_the_events_runners_on_the_series_read(
    client: Client, auth_headers: Headers, member: Member
) -> None:
    event, stage, organizer, _ = hidden_cup(client, auth_headers, member)
    drawn = client.post(f"/events/{event}/stages/{stage}/generate", headers=organizer)
    assert drawn.status_code == 200, drawn.text
    path = f"/events/{event}/stages/{stage}/series"

    anonymous = client.get(path)

    assert anonymous.status_code == 200, anonymous.text
    rows = anonymous.json()["series"]
    assert len(rows) == 3
    assert {(row["entrant1_seed"], row["entrant2_seed"]) for row in rows} == {
        (None, None)
    }
    assert anonymous.headers["Cache-Control"].startswith("public")
    other = client.get(path, headers=member("51")).json()["series"]
    assert {(row["entrant1_seed"], row["entrant2_seed"]) for row in other} == {
        (None, None)
    }
    for headers in (organizer, auth_headers):
        first = client.get(path, headers=headers).json()["series"][0]
        assert (first["entrant1_seed"], first["entrant2_seed"]) == (1, 4)
    shown = client.put(
        f"/events/{event}", json={"hide_seeds": False}, headers=organizer
    )
    assert shown.status_code == 200, shown.text
    first = client.get(path).json()["series"][0]
    assert (first["entrant1_seed"], first["entrant2_seed"]) == (1, 4)


def test_the_hide_switch_and_the_stage_seed_source_round_trip(
    client: Client, auth_headers: Headers
) -> None:
    made = client.post(
        "/events",
        json={
            "name": "Hidden Cup",
            "kind": "cup",
            "hide_seeds": True,
            "stages": [STAGES[0] | {"seed_source": "manual"}],
        },
        headers=auth_headers,
    )
    assert made.status_code == 201, made.text
    event = made.json()["id"]

    read = client.get(f"/events/{event}", headers=auth_headers).json()

    assert read["hide_seeds"] is True
    assert read["stages"][0]["seed_source"] == "manual"
    changed = client.put(
        f"/events/{event}", json={"hide_seeds": False}, headers=auth_headers
    )
    assert changed.json()["hide_seeds"] is False
    assert changed.json()["stages"][0]["seed_source"] == "manual"
    wrong = client.put(
        f"/events/{event}/stages",
        json=[STAGES[0] | {"seed_source": "qualifier"}],
        headers=auth_headers,
    )
    assert wrong.status_code == 422
