"""A cup played over rounds: each round a competition of its own, one overall table.

A cup made with rounds copies its stages into every round, turns the cup-wide
check-in off and checks its players in per round. A round draws the players
checked in for it, and a format edit reaches every round alike. A finished
round pays points per place into the overall table, which breaks a tie on the
best single place, and finishing the cup pays its awards from that table.
"""

from typing import Any

from httpx2 import Client

from app.core.db import Session
from app.models.enums import Race
from app.models.user import User
from app.models.w3c_stats import W3CStats
from tests.test_awards import play_out
from tests.test_cup_divisions import field_of, make_cup
from tests.test_event_divisions import enter
from tests.test_event_organizers import Headers
from tests.test_stage_engine import bracket, generate, score

LEGS = [
    {"starts_at": "2026-11-06T19:00:00Z"},
    {"starts_at": "2026-11-13T19:00:00Z"},
    {"starts_at": "2026-11-20T19:00:00Z", "name": "Finale"},
]


def rounds_cup(client: Client, headers: Headers, **fields: Any) -> dict[str, Any]:  # noqa: ANN401
    return make_cup(client, headers, legs=LEGS, **fields)


def legs_of(client: Client, event: int) -> list[dict[str, Any]]:
    return client.get(f"/events/{event}").json()["cup_legs"]


def check_in(
    client: Client, headers: Headers, event: int, leg: int, entrant: int | None = None
) -> Any:  # noqa: ANN401
    return client.post(
        f"/events/{event}/legs/{leg}/checkins",
        json={"entrant_id": entrant},
        headers=headers,
    )


def finish_leg(client: Client, headers: Headers, event: int, leg: int) -> Any:  # noqa: ANN401
    return client.post(f"/events/{event}/legs/{leg}/finish", headers=headers)


def player_with_login(discord_id: str, mmr: int) -> int:
    """A player whose login names it, so its own check-in finds its entry."""
    with Session.begin() as session:
        user = User(
            name=f"P{discord_id}",
            discordTag="",
            discordId=discord_id,
            race=Race.HU,
        )
        session.add(user)
        session.flush()
        assert user.id is not None
        session.add(
            W3CStats(user_id=user.id, race=Race.HU, wc3_season=22, games=100, mmr=mmr)
        )
        return user.id


def test_a_cup_made_with_rounds_copies_its_stages_into_every_round(
    client: Client, auth_headers: Headers
) -> None:
    cup = rounds_cup(client, auth_headers)
    read = client.get(f"/events/{cup['id']}").json()

    assert read["checkin_enabled"] is False
    legs = read["cup_legs"]
    assert [(leg["number"], leg["name"]) for leg in legs] == [
        (1, "Round 1"),
        (2, "Round 2"),
        (3, "Finale"),
    ]
    assert [leg["starts_at"][:10] for leg in legs] == [
        "2026-11-06",
        "2026-11-13",
        "2026-11-20",
    ]
    assert [stage["id"] for stage in read["stages"]] == [
        stage for leg in legs for stage in leg["stage_ids"]
    ]
    assert {stage["format"] for stage in read["stages"]} == {"single_elimination"}

    # a cup of one evening reads no rounds
    plain = make_cup(client, auth_headers, name="One Evening Cup")
    assert client.get(f"/events/{plain['id']}").json()["cup_legs"] is None


def test_a_cup_takes_two_rounds_or_more(client: Client, auth_headers: Headers) -> None:
    from tests.test_event_organizers import CUP

    response = client.post(
        "/events", json=CUP | {"legs": LEGS[:1]}, headers=auth_headers
    )
    assert response.status_code == 400, response.text


def test_a_round_draws_the_players_checked_in_for_it(
    client: Client, auth_headers: Headers
) -> None:
    cup = rounds_cup(client, auth_headers)
    entrants = field_of(cup["id"], (2000, 1900, 1800, 1700, 1600))
    first = legs_of(client, cup["id"])[0]
    for entrant in entrants[:4]:
        assert (
            check_in(client, auth_headers, cup["id"], first["id"], entrant).status_code
            == 200
        )

    generate(client, auth_headers, cup["id"], first["stage_ids"][0])

    drawn = bracket(first["stage_ids"][0])
    assert len([row for row in drawn if row["round"] != "Final"]) == 2
    late = check_in(client, auth_headers, cup["id"], first["id"], entrants[4])
    assert late.status_code == 400, late.text
    assert late.json() == {"error": "This round is drawn; its players are set"}


def test_a_player_checks_in_their_own_entry_alone(
    client: Client,
    auth_headers: Headers,
    member: Any,  # noqa: ANN401
) -> None:
    cup = rounds_cup(client, auth_headers)
    mine = enter(cup["id"], player_with_login("71", 1800))
    other = enter(cup["id"], player_with_login("72", 1700))
    leg = legs_of(client, cup["id"])[0]["id"]
    headers = member("71")

    own = check_in(client, headers, cup["id"], leg)
    assert own.status_code == 200, own.text
    assert own.json()[0]["checked_in"] == [mine]
    refused = check_in(client, headers, cup["id"], leg, other)
    assert refused.status_code == 403, refused.text

    out = client.delete(f"/events/{cup['id']}/legs/{leg}/checkins", headers=headers)
    assert out.status_code == 200, out.text
    assert out.json()[0]["checked_in"] == []


def test_the_overall_table_adds_the_points_of_every_finished_round(
    client: Client, auth_headers: Headers
) -> None:
    cup = rounds_cup(client, auth_headers, points_by_place=[10, 6, 3, 3])
    field_of(cup["id"], (2000, 1900, 1800, 1700))
    legs = legs_of(client, cup["id"])
    for leg in legs[:2]:
        everyone = client.post(
            f"/events/{cup['id']}/legs/{leg['id']}/checkins/everyone",
            headers=auth_headers,
        )
        assert len(everyone.json()[leg["number"] - 1]["checked_in"]) == 4
        stage = leg["stage_ids"][0]
        # a round with a series still open does not finish
        generate(client, auth_headers, cup["id"], stage)
        early = finish_leg(client, auth_headers, cup["id"], leg["id"])
        assert early.status_code == 400, early.text
        play_out(client, auth_headers, stage)
        done = finish_leg(client, auth_headers, cup["id"], leg["id"])
        assert done.status_code == 200, done.text

    overall = client.get(f"/events/{cup['id']}/overall").json()
    assert overall["points_by_place"] == [10, 6, 3, 3]
    rows = overall["rows"]
    # the first side takes every series, so the same seeds place alike in both
    # rounds; the two semi-final losers level on points part on their best place
    assert [row["points"] for row in rows] == [20, 12, 6, 6]
    assert [row["position"] for row in rows] == [1, 2, 3, 4]
    assert [row["best"] for row in rows] == [1, 2, 3, 4]
    assert all(len(row["legs"]) == 2 for row in rows)

    awards = client.post(f"/events/{cup['id']}/finish", headers=auth_headers)
    assert awards.status_code == 200, awards.text
    assert [(row["place"], row["entrant_id"]) for row in awards.json()] == [
        (row["position"], row["entrant_id"]) for row in rows
    ]


def test_a_tie_on_points_breaks_on_the_best_single_place(
    client: Client, auth_headers: Headers
) -> None:
    cup = rounds_cup(client, auth_headers, points_by_place=[10, 5, 0, 0])
    entrants = field_of(cup["id"], (2000, 1900, 1800, 1700))
    legs = legs_of(client, cup["id"])
    # round 1: the field plays; round 2: two players alone, the other side wins
    client.post(
        f"/events/{cup['id']}/legs/{legs[0]['id']}/checkins/everyone",
        headers=auth_headers,
    )
    generate(client, auth_headers, cup["id"], legs[0]["stage_ids"][0])
    play_out(client, auth_headers, legs[0]["stage_ids"][0])
    finish_leg(client, auth_headers, cup["id"], legs[0]["id"])
    first = client.get(f"/events/{cup['id']}/overall").json()["rows"]
    winner, second = first[0]["entrant_id"], first[1]["entrant_id"]
    winner_user = first[0]["user"]["id"]
    for entrant in (winner, second):
        check_in(client, auth_headers, cup["id"], legs[1]["id"], entrant)
    stage = legs[1]["stage_ids"][0]
    generate(client, auth_headers, cup["id"], stage)
    (final,) = bracket(stage)
    # the round-1 winner loses the final of round 2
    result = (0, 2) if final["sides"][0] == winner_user else (2, 0)
    assert score(client, auth_headers, final["id"], *result).status_code == 200
    finish_leg(client, auth_headers, cup["id"], legs[1]["id"])

    rows = client.get(f"/events/{cup['id']}/overall").json()["rows"]
    # both hold 15 points: one place 1 apiece, so the tie stays shared
    assert [(row["points"], row["position"]) for row in rows[:2]] == [(15, 1), (15, 1)]
    assert {row["entrant_id"] for row in rows[:2]} == {winner, second}
    assert set(entrants) >= {row["entrant_id"] for row in rows}


def test_a_format_edit_reaches_every_round(
    client: Client, auth_headers: Headers
) -> None:
    cup = rounds_cup(client, auth_headers)
    one_round = [{"format": "single_elimination", "best_of": 5}]
    edited = client.put(
        f"/events/{cup['id']}/stages", json=one_round, headers=auth_headers
    )
    assert edited.status_code == 200, edited.text
    assert [stage["best_of"] for stage in edited.json()["stages"]] == [5, 5, 5]

    more = client.put(
        f"/events/{cup['id']}/stages", json=one_round * 2, headers=auth_headers
    )
    assert more.status_code == 400, more.text


def test_a_signup_after_the_first_draw_joins_the_later_rounds(
    client: Client, auth_headers: Headers
) -> None:
    cup = rounds_cup(client, auth_headers)
    field_of(cup["id"], (2000, 1900))
    first = legs_of(client, cup["id"])[0]
    client.post(
        f"/events/{cup['id']}/legs/{first['id']}/checkins/everyone",
        headers=auth_headers,
    )
    generate(client, auth_headers, cup["id"], first["stage_ids"][0])
    from app.services.events import _waits

    with Session.begin() as session:
        from app.models.season import Season

        event = session.get(Season, cup["id"])
        assert event is not None
        assert _waits(session, event) is False


def test_a_round_seeds_the_players_checked_in_for_it_alone(
    client: Client, auth_headers: Headers
) -> None:
    cup = rounds_cup(client, auth_headers)
    entrants = field_of(cup["id"], (2000, 1900, 1800, 1700, 1600))
    first = legs_of(client, cup["id"])[0]
    # the strongest player sits this round out
    for entrant in entrants[1:]:
        check_in(client, auth_headers, cup["id"], first["id"], entrant)

    generate(client, auth_headers, cup["id"], first["stage_ids"][0])

    seeds = {
        row["id"]: row["seed"]
        for row in client.get(
            f"/events/{cup['id']}/entrants", headers=auth_headers
        ).json()
    }
    assert seeds[entrants[0]] is None
    assert sorted(seeds[entrant] for entrant in entrants[1:]) == [1, 2, 3, 4]


def test_a_finished_round_keeps_its_draw(client: Client, auth_headers: Headers) -> None:
    cup = rounds_cup(client, auth_headers)
    field_of(cup["id"], (2000, 1900))
    first = legs_of(client, cup["id"])[0]
    stage = first["stage_ids"][0]
    client.post(
        f"/events/{cup['id']}/legs/{first['id']}/checkins/everyone",
        headers=auth_headers,
    )
    generate(client, auth_headers, cup["id"], stage)
    play_out(client, auth_headers, stage)
    assert finish_leg(client, auth_headers, cup["id"], first["id"]).status_code == 200

    undone = client.delete(
        f"/events/{cup['id']}/stages/{stage}/series?confirm=true", headers=auth_headers
    )
    assert undone.status_code == 400, undone.text
    reopened = client.delete(
        f"/events/{cup['id']}/legs/{first['id']}/finish", headers=auth_headers
    )
    assert reopened.json()[0]["finished_at"] is None


def test_a_round_takes_a_new_name_and_start_in_order(
    client: Client, auth_headers: Headers
) -> None:
    cup = rounds_cup(client, auth_headers)
    first, second, third = legs_of(client, cup["id"])

    moved = client.put(
        f"/events/{cup['id']}/legs/{second['id']}",
        json={"name": "Semi round", "starts_at": "2026-11-14T18:00:00Z"},
        headers=auth_headers,
    )
    assert moved.status_code == 200, moved.text
    assert (moved.json()[1]["name"], moved.json()[1]["starts_at"][:16]) == (
        "Semi round",
        "2026-11-14T18:00",
    )
    # a round never starts before the one ahead of it
    early = client.put(
        f"/events/{cup['id']}/legs/{third['id']}",
        json={"starts_at": "2026-11-10T19:00:00Z"},
        headers=auth_headers,
    )
    assert early.status_code == 400, early.text
    # an empty name goes back to the round's number
    named = client.put(
        f"/events/{cup['id']}/legs/{second['id']}",
        json={"name": ""},
        headers=auth_headers,
    )
    assert named.json()[1]["name"] == "Round 2"
    # the first round's start is the cup's start, both ways
    client.put(
        f"/events/{cup['id']}/legs/{first['id']}",
        json={"starts_at": "2026-11-05T19:00:00Z"},
        headers=auth_headers,
    )
    assert (
        client.get(f"/events/{cup['id']}")
        .json()["starts_at"]
        .startswith("2026-11-05T19:00")
    )
    client.put(
        f"/events/{cup['id']}",
        json={"starts_at": "2026-11-04T20:00:00Z"},
        headers=auth_headers,
    )
    assert legs_of(client, cup["id"])[0]["starts_at"].startswith("2026-11-04T20:00")


def test_a_round_is_added_after_the_last_with_the_same_stages(
    client: Client, auth_headers: Headers
) -> None:
    cup = rounds_cup(client, auth_headers)

    added = client.post(
        f"/events/{cup['id']}/legs",
        json={"starts_at": "2026-11-27T19:00:00Z"},
        headers=auth_headers,
    )

    assert added.status_code == 201, added.text
    legs = added.json()
    assert [(leg["number"], leg["name"]) for leg in legs][-1] == (4, "Round 4")
    stages = client.get(f"/events/{cup['id']}").json()["stages"]
    assert len(stages) == 4
    assert [stage["id"] for stage in stages][-1] == legs[-1]["stage_ids"][0]
    assert stages[-1]["format"] == stages[0]["format"]
    before = client.post(
        f"/events/{cup['id']}/legs",
        json={"starts_at": "2026-11-20T19:00:00Z"},
        headers=auth_headers,
    )
    assert before.status_code == 400, before.text


def test_a_round_not_drawn_goes_and_the_later_ones_move_up(
    client: Client, auth_headers: Headers
) -> None:
    cup = rounds_cup(client, auth_headers)
    field_of(cup["id"], (2000, 1900))
    first, second, third = legs_of(client, cup["id"])
    client.post(
        f"/events/{cup['id']}/legs/{first['id']}/checkins/everyone",
        headers=auth_headers,
    )
    generate(client, auth_headers, cup["id"], first["stage_ids"][0])

    drawn = client.delete(
        f"/events/{cup['id']}/legs/{first['id']}", headers=auth_headers
    )
    assert drawn.status_code == 400, drawn.text

    gone = client.delete(
        f"/events/{cup['id']}/legs/{second['id']}", headers=auth_headers
    )
    assert gone.status_code == 200, gone.text
    assert [(leg["number"], leg["name"]) for leg in gone.json()] == [
        (1, "Round 1"),
        (2, "Finale"),
    ]
    stages = client.get(f"/events/{cup['id']}").json()["stages"]
    assert [stage["position"] for stage in stages] == [1, 2]
    last = client.delete(
        f"/events/{cup['id']}/legs/{third['id']}", headers=auth_headers
    )
    assert last.status_code == 400, last.text
    assert last.json() == {"error": "A cup over rounds keeps two rounds or more"}
