"""A custom game cup: one map, no veto, every game of a series on it.

An organizer names the custom map in Create cup: the app's map of that name,
or a new map marked `custom`. The cup holds that one map, vetoes nothing, and
every game of every series is played on it; a free for all custom cup's
lobbies play it too. The pool of a custom game cup stays one map.
"""

from typing import Any

from httpx2 import Client

from app.core.db import Session
from tests.test_cup_best_of import maps
from tests.test_cup_divisions import field_of, make_cup, stage_of
from tests.test_event_organizers import Headers, grant
from tests.test_stage_engine import bracket, generate


def custom_cup(
    client: Client,
    headers: Headers,
    map_id: int,
    **fields: Any,  # noqa: ANN401
) -> dict[str, Any]:
    return make_cup(
        client,
        headers,
        name=fields.pop("name", "Custom Night"),
        map_ids=[map_id],
        custom_game=True,
        veto_by_best_of=True,
        **fields,
    )


def test_an_organizer_names_a_custom_map_once(
    client: Client,
    auth_headers: Headers,
    member: Any,  # noqa: ANN401
) -> None:
    grant(client, auth_headers, "70")
    organizer = member("70")

    made = client.post(
        "/maps/custom", json={"name": "Footmen Frenzy"}, headers=organizer
    )
    assert made.status_code == 201, made.text
    assert (made.json()["name"], made.json()["modes"]) == ("Footmen Frenzy", "custom")
    # the same name, in other case and spaces, finds the same map
    again = client.post(
        "/maps/custom", json={"name": "  footmen frenzy "}, headers=organizer
    )
    assert again.json()["id"] == made.json()["id"]
    # a map the app holds under that short name is found, not doubled
    with Session.begin() as session:
        from app.models.map import Map

        session.add(Map(name="Legion TD Mega", shortname="LTD"))
    found = client.post("/maps/custom", json={"name": "ltd"}, headers=organizer)
    assert found.json()["name"] == "Legion TD Mega"
    refused = client.post(
        "/maps/custom", json={"name": "Anything"}, headers=member("71")
    )
    assert refused.status_code == 403, refused.text


def test_a_custom_cup_plays_every_game_on_its_one_map(
    client: Client, auth_headers: Headers
) -> None:
    (map_id,) = maps(1)
    cup = custom_cup(client, auth_headers, map_id)
    read = client.get(f"/events/{cup['id']}").json()
    assert (read["custom_game"], read["veto_by_best_of"]) == (True, False)
    field_of(cup["id"], (2000, 1900, 1800, 1700))
    generate(client, auth_headers, cup["id"], stage_of(cup))

    series = client.get(f"/events/{cup['id']}/stages/{stage_of(cup)}/series").json()[
        "series"
    ]
    first = next(row for row in series if row["entrant1_id"] and row["entrant2_id"])
    assert first["rules"]["map_rules"] == "fixed,fixed,fixed"
    board = client.get(f"/cup-series/{first['id']}/veto", headers=auth_headers).json()
    assert board["week_map_id"] == map_id

    plain = make_cup(client, auth_headers, name="Plain Night")
    assert client.get(f"/events/{plain['id']}").json()["custom_game"] is False


def test_a_custom_cup_holds_one_map(client: Client, auth_headers: Headers) -> None:
    one, two = maps(2)
    for pool in ([], [one, two]):
        refused = client.post(
            "/events",
            json={
                "name": f"Custom {len(pool)}",
                "kind": "cup",
                "custom_game": True,
                "map_ids": pool,
                "stages": [{"format": "single_elimination", "best_of": 1}],
            },
            headers=auth_headers,
        )
        assert refused.status_code == 400, refused.text
    cup = custom_cup(client, auth_headers, one)
    url = f"/events/{cup['id']}/maps"
    assert (
        client.put(url, json={"map_ids": [one, two]}, headers=auth_headers).status_code
        == 400
    )
    swapped = client.put(url, json={"map_ids": [two]}, headers=auth_headers)
    assert swapped.status_code == 200, swapped.text


def test_a_custom_ffa_plays_its_lobbies_on_the_one_map(
    client: Client, auth_headers: Headers
) -> None:
    (map_id,) = maps(1)
    cup = custom_cup(
        client,
        auth_headers,
        map_id,
        name="Custom FFA",
        stages=[
            {
                "format": "ffa",
                "best_of": 1,
                "lobby_size": 4,
                "group_advance": 2,
                "points_by_place": "4,3,2,1",
                "scheduling_mode": "immediate",
            }
        ],
    )
    field_of(cup["id"], (2000, 1900, 1800, 1700, 1600, 1500, 1400, 1300))
    generate(client, auth_headers, cup["id"], stage_of(cup))

    lobbies = client.get(f"/events/{cup['id']}/stages/{stage_of(cup)}/series").json()[
        "series"
    ]
    assert {row["lobby_map"]["id"] for row in lobbies} == {map_id}
    assert len(bracket(stage_of(cup))) == 3
