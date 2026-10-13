"""A cup's seeds change after its draw, and the draw follows them at once.

A seed write on a cup's drawn first stage takes the draw back, writes the
seeds and draws the stage again in one transaction, so the bracket always
reads the seeds it shows. A stage whose series hold results asks to confirm,
as undoing the draw does, a later stage has no seeds of its own to change, and
a stage that pairs by round draws its first round again.
"""

from typing import Any

from httpx2 import Client

from tests.test_cup_divisions import field_of, make_cup, stage_of
from tests.test_event_divisions import set_divisions
from tests.test_event_organizers import Headers
from tests.test_stage_engine import bracket, generate, score


def redraw(
    client: Client,
    headers: Headers,
    cup: dict[str, Any],
    body: dict[str, Any],
    **query: str,
) -> Any:  # noqa: ANN401
    return client.put(
        f"/events/{cup['id']}/stages/{stage_of(cup)}/seeds/redraw",
        params=query,
        json=body,
        headers=headers,
    )


def users_of(client: Client, headers: Headers, cup: dict[str, Any]) -> dict[int, int]:
    """Each entrant's user, to read a bracket's sides by entrant."""
    rows = client.get(f"/events/{cup['id']}/entrants", headers=headers).json()
    return {row["id"]: row["user"]["id"] for row in rows}


def first_round(stage: int) -> list[tuple[int | None, int | None]]:
    rows = bracket(stage)
    first = min(row["number"] for row in rows)
    return [row["sides"] for row in rows if row["number"] == first]


def test_a_new_order_draws_the_bracket_again(
    client: Client, auth_headers: Headers
) -> None:
    cup = make_cup(client, auth_headers)
    a, b, c, d = field_of(cup["id"], (2000, 1900, 1800, 1700))
    generate(client, auth_headers, cup["id"], stage_of(cup))
    user = users_of(client, auth_headers, cup)

    answer = redraw(
        client, auth_headers, cup, {"source": "manual", "order": [d, c, b, a]}
    )

    assert answer.status_code == 200, answer.text
    assert [(row["id"], row["seed"]) for row in answer.json()] == [
        (d, 1),
        (c, 2),
        (b, 3),
        (a, 4),
    ]
    # seed 1 meets seed 4, and seed 2 meets seed 3
    assert {frozenset(pair) for pair in first_round(stage_of(cup))} == {
        frozenset((user[d], user[a])),
        frozenset((user[c], user[b])),
    }
    stage = client.get(f"/events/{cup['id']}").json()["stages"][0]
    assert stage["seeds_locked_at"] is not None


def test_a_result_asks_to_confirm_and_goes_with_the_old_draw(
    client: Client, auth_headers: Headers
) -> None:
    cup = make_cup(client, auth_headers)
    a, b, c, d = field_of(cup["id"], (2000, 1900, 1800, 1700))
    generate(client, auth_headers, cup["id"], stage_of(cup))
    played = bracket(stage_of(cup))[0]
    assert score(client, auth_headers, played["id"], 2, 0).status_code == 200
    body = {"source": "manual", "order": [b, a, d, c]}

    asked = redraw(client, auth_headers, cup, body)
    assert asked.status_code == 409, asked.text
    assert "confirm" in asked.json()["error"]
    # the refusal keeps the draw and its result
    assert any(row["score"] == (2, 0) for row in bracket(stage_of(cup)))

    confirmed = redraw(client, auth_headers, cup, body, confirm="true")
    assert confirmed.status_code == 200, confirmed.text
    assert all(row["score"] == (None, None) for row in bracket(stage_of(cup)))


def test_a_pinned_seed_stays_through_a_reshuffle_after_the_draw(
    client: Client, auth_headers: Headers
) -> None:
    cup = make_cup(client, auth_headers)
    entrants = field_of(cup["id"], (2000, 1900, 1800, 1700, 1600, 1500))
    generate(client, auth_headers, cup["id"], stage_of(cup))
    pinned = entrants[0]
    client.put(
        f"/events/{cup['id']}/entrants/{pinned}/pins",
        json={"seed_pinned": True},
        headers=auth_headers,
    )

    for _ in range(3):
        answer = redraw(client, auth_headers, cup, {"source": "random"})
        assert answer.status_code == 200, answer.text
        seeds = {row["id"]: row["seed"] for row in answer.json()}
        assert seeds[pinned] == 1
        assert sorted(seeds.values()) == [1, 2, 3, 4, 5, 6]


def test_a_division_reseeds_alone_and_the_stage_draws_again(
    client: Client, auth_headers: Headers
) -> None:
    cup = make_cup(client, auth_headers, uses_divisions=True)
    field_of(cup["id"], (2000, 1950, 1900, 1850, 1500, 1450, 1400, 1350))
    set_divisions(
        client,
        cup["id"],
        [{"name": "Top", "lower_bound": 1800}, {"name": "Rest"}],
        auth_headers,
    )
    client.post(f"/events/{cup['id']}/divisions/assign", headers=auth_headers)
    generate(client, auth_headers, cup["id"], stage_of(cup))
    divisions = client.get(f"/events/{cup['id']}").json()["divisions"]
    top, rest = (row["id"] for row in divisions)
    before = {
        row["id"]: row["seed"]
        for row in client.get(
            f"/events/{cup['id']}/entrants", headers=auth_headers
        ).json()
        if row["division_id"] == rest
    }
    top_rows = [
        row["id"]
        for row in client.get(
            f"/events/{cup['id']}/entrants", headers=auth_headers
        ).json()
        if row["division_id"] == top
    ]

    answer = redraw(
        client,
        auth_headers,
        cup,
        {"source": "manual", "order": list(reversed(top_rows)), "division_id": top},
    )

    assert answer.status_code == 200, answer.text
    assert {row["division_id"] for row in answer.json()} == {top}
    after = {
        row["id"]: row["seed"]
        for row in client.get(
            f"/events/{cup['id']}/entrants", headers=auth_headers
        ).json()
        if row["division_id"] == rest
    }
    assert after == before
    assert {row["division_id"] for row in bracket(stage_of(cup))} == {top, rest}


def test_a_swiss_stage_draws_its_first_round_again(
    client: Client, auth_headers: Headers
) -> None:
    cup = make_cup(
        client,
        auth_headers,
        stages=[
            {
                "format": "swiss",
                "best_of": 1,
                "swiss_rounds": 3,
                "scheduling_mode": "immediate",
                "advance_count": 2,
                "auto_advance": True,
            },
            {"name": "Playoff", "format": "single_elimination", "best_of": 1},
        ],
    )
    a, b, c, d = field_of(cup["id"], (2000, 1900, 1800, 1700))
    swiss, playoff = (row["id"] for row in cup["stages"])
    drew = client.post(
        f"/events/{cup['id']}/stages/{swiss}/rounds", headers=auth_headers
    )
    assert drew.status_code == 200, drew.text

    answer = redraw(
        client, auth_headers, cup, {"source": "manual", "order": [d, c, b, a]}
    )

    assert answer.status_code == 200, answer.text
    assert len({row["number"] for row in bracket(swiss)}) == 1
    later = client.put(
        f"/events/{cup['id']}/stages/{playoff}/seeds/redraw",
        json={"source": "mmr"},
        headers=auth_headers,
    )
    assert later.status_code == 400, later.text


def test_an_undrawn_stage_is_drawn_by_the_same_write(
    client: Client, auth_headers: Headers
) -> None:
    cup = make_cup(client, auth_headers)
    field_of(cup["id"], (2000, 1900, 1800, 1700))

    answer = redraw(client, auth_headers, cup, {"source": "mmr"})

    assert answer.status_code == 200, answer.text
    assert len(bracket(stage_of(cup))) == 3
