"""Edit cup: a cup's settings change until its draw, its game mode until its first sign-up.

Edit cup saves the event fields, the stages, the map pool, the custom game
choice and the points table in one write, so the pool is checked against the
stages once both are in. The game mode, the team size, the entrant kind, the
custom game and free for all against head to head, changes until anyone signs
up. The format and the pool change until the draw, and the points table of a
cup over rounds until a round is drawn. Before that draw a cup over rounds may
also change how many stages a round plays.
"""

from typing import Any

from httpx2 import Client

from app.models.enums import Race
from tests.test_cup_best_of import maps
from tests.test_cup_divisions import field_of, make_cup, stage_of
from tests.test_cup_rounds import LEGS, check_in, legs_of, rounds_cup
from tests.test_event_divisions import add_player, enter
from tests.test_event_organizers import Headers, grant
from tests.test_events import add_event
from tests.test_stage_engine import generate

MODE_LOCKED = {"error": "Players have signed up, so the cup's game mode stays"}
FORMAT_DRAWN = {
    "error": "The cup is drawn, so its format and maps are set; undo the draw to change them"
}
SE = {"format": "single_elimination", "best_of": 1, "scheduling_mode": "immediate"}
FFA = {
    "format": "ffa",
    "best_of": 1,
    "scheduling_mode": "immediate",
    "lobby_size": 4,
    "group_advance": 2,
}


def edit(client: Client, headers: Headers, event: int, **body: Any) -> Any:  # noqa: ANN401
    return client.put(f"/events/{event}", json=body, headers=headers)


def test_an_organizer_saves_the_format_and_pool_in_one_write(
    client: Client,
    auth_headers: Headers,
    member: Any,  # noqa: ANN401
) -> None:
    grant(client, auth_headers, "80")
    organizer = member("80")
    one, *more = maps(5)
    cup = make_cup(client, organizer, stages=[SE], map_ids=[one], veto_by_best_of=True)
    # the stages alone would need five maps before the pool holds them
    alone = client.put(
        f"/events/{cup['id']}/stages", json=[SE | {"best_of": 5}], headers=organizer
    )
    assert alone.status_code == 400, alone.text

    saved = edit(
        client,
        organizer,
        cup["id"],
        name="Friday Night Cup #2",
        stages=[SE | {"best_of": 5}],
        map_ids=[one, *more],
    )

    assert saved.status_code == 200, saved.text
    read = client.get(f"/events/{cup['id']}").json()
    assert (read["name"], read["stages"][0]["best_of"], len(read["maps"])) == (
        "Friday Night Cup #2",
        5,
        5,
    )
    assert read["drawn"] is False


def test_the_game_mode_changes_until_the_first_sign_up(
    client: Client, auth_headers: Headers
) -> None:
    (map_id,) = maps(1)
    cup = make_cup(client, auth_headers, stages=[SE], map_ids=[map_id])
    teams = edit(client, auth_headers, cup["id"], entrant_kind="team", team_size=2)
    assert teams.status_code == 200, teams.text
    assert teams.json()["team_size"] == 2
    solo = edit(client, auth_headers, cup["id"], entrant_kind="solo", team_size=None)
    assert solo.status_code == 200, solo.text
    lobbies = edit(client, auth_headers, cup["id"], stages=[FFA])
    assert lobbies.status_code == 200, lobbies.text
    assert lobbies.json()["ffa"] is True
    assert edit(client, auth_headers, cup["id"], stages=[SE]).status_code == 200

    enter(cup["id"], add_player("Early bird", {Race.HU: 1500}))

    for body in (
        {"entrant_kind": "team", "team_size": 2},
        {"custom_game": True, "map_ids": [map_id]},
        {"stages": [FFA]},
    ):
        refused = edit(client, auth_headers, cup["id"], **body)
        assert refused.status_code == 409, body
        assert refused.json() == MODE_LOCKED
    by_stages = client.put(
        f"/events/{cup['id']}/stages", json=[FFA], headers=auth_headers
    )
    assert by_stages.status_code == 409, by_stages.text
    # what keeps the mode still changes
    kept = edit(
        client,
        auth_headers,
        cup["id"],
        entrant_kind="solo",
        custom_game=False,
        stages=[SE | {"best_of": 1, "third_place": True}],
    )
    assert kept.status_code == 200, kept.text


def test_a_custom_game_turns_on_with_one_map_and_vetoes_nothing(
    client: Client, auth_headers: Headers
) -> None:
    pool = maps(3)
    cup = make_cup(
        client,
        auth_headers,
        stages=[SE | {"best_of": 3}],
        map_ids=pool,
        veto_by_best_of=True,
    )

    two = edit(client, auth_headers, cup["id"], custom_game=True, map_ids=pool[:2])
    assert two.status_code == 400, two.text
    assert two.json() == {"error": "A custom game cup is played on one map"}
    custom = edit(client, auth_headers, cup["id"], custom_game=True, map_ids=pool[:1])
    assert custom.status_code == 200, custom.text
    assert (custom.json()["custom_game"], custom.json()["veto_by_best_of"]) == (
        True,
        False,
    )

    back = edit(
        client,
        auth_headers,
        cup["id"],
        custom_game=False,
        veto_by_best_of=True,
        map_ids=pool,
    )
    assert back.status_code == 200, back.text
    assert (back.json()["custom_game"], back.json()["veto_by_best_of"]) == (
        False,
        True,
    )


def test_a_drawn_cup_keeps_its_format_and_pool(
    client: Client, auth_headers: Headers
) -> None:
    pool = maps(3)
    cup = make_cup(client, auth_headers, stages=[SE], map_ids=pool)
    field_of(cup["id"], (2000, 1900, 1800, 1700))
    generate(client, auth_headers, cup["id"], stage_of(cup))
    assert client.get(f"/events/{cup['id']}").json()["drawn"] is True

    for body in ({"stages": [SE | {"best_of": 3}]}, {"map_ids": pool[:1]}):
        refused = edit(client, auth_headers, cup["id"], **body)
        assert refused.status_code == 409, body
        assert refused.json() == FORMAT_DRAWN
    # the fields beside them still change
    assert (
        edit(client, auth_headers, cup["id"], description="Bring snacks").status_code
        == 200
    )


def test_the_points_table_changes_until_a_round_is_drawn(
    client: Client, auth_headers: Headers
) -> None:
    cup = rounds_cup(client, auth_headers)
    assert client.get(f"/events/{cup['id']}").json()["points_by_place"] == [
        10,
        8,
        6,
        5,
        4,
        3,
        2,
        1,
    ]
    saved = edit(client, auth_headers, cup["id"], points_by_place=[5, 3, 1])
    assert saved.status_code == 200, saved.text
    assert saved.json()["points_by_place"] == [5, 3, 1]

    entrants = field_of(cup["id"], (2000, 1900))
    first = legs_of(client, cup["id"])[0]
    for entrant in entrants:
        check_in(client, auth_headers, cup["id"], first["id"], entrant)
    generate(client, auth_headers, cup["id"], first["stage_ids"][0])

    late = edit(client, auth_headers, cup["id"], points_by_place=[3, 2, 1])
    assert late.status_code == 409, late.text
    assert late.json() == {"error": "A round is drawn, so the points table stays"}
    evening = make_cup(client, auth_headers, name="One evening")
    refused = edit(client, auth_headers, evening["id"], points_by_place=[3, 2, 1])
    assert refused.status_code == 400, refused.text


def test_a_cup_over_rounds_changes_its_stages_per_round_before_the_draw(
    client: Client, auth_headers: Headers
) -> None:
    league = {"format": "round_robin", "best_of": 1, "scheduling_mode": "immediate"}
    # two rounds of one stage hold two stages, as many as the body: still one round's stages
    cup = make_cup(client, auth_headers, legs=LEGS[:2], stages=[league])
    playoff = SE | {"name": "Playoff"}

    saved = edit(
        client,
        auth_headers,
        cup["id"],
        stages=[league | {"advance_count": 2, "auto_advance": True}, playoff],
    )

    assert saved.status_code == 200, saved.text
    legs = saved.json()["cup_legs"]
    assert [len(leg["stage_ids"]) for leg in legs] == [2, 2]
    assert [stage["format"] for stage in saved.json()["stages"]] == [
        "round_robin",
        "single_elimination",
    ] * 2

    entrants = field_of(cup["id"], (2000, 1900, 1800, 1700))
    for entrant in entrants:
        check_in(client, auth_headers, cup["id"], legs[0]["id"], entrant)
    generate(client, auth_headers, cup["id"], legs[0]["stage_ids"][0])
    refused = client.put(
        f"/events/{cup['id']}/stages", json=[league], headers=auth_headers
    )
    assert refused.status_code == 409, refused.text


def test_only_a_cup_takes_the_cup_settings(
    client: Client, auth_headers: Headers
) -> None:
    event = add_event(name="Not a cup")

    refused = edit(client, auth_headers, event, custom_game=True)

    assert refused.status_code == 400, refused.text
    assert refused.json() == {"error": "Only a cup takes these settings"}
    assert client.get(f"/events/{event}").json()["drawn"] is None
