"""The fantasy score breakdown names races by their plain value.

The breakdown is read by the public fantasy page, which prints
race_breakdown.race straight into the markup and passes it to RaceIcon,
where it is matched against the ids in the frontend's races.js. A value
carrying the enum repr, "Race.HU", printed as that text and matched
nothing, so the icon rendered as blank.
"""

import json
from typing import Any

from httpx2 import Client


def breakdown(client: Client, seeded: dict[str, Any]) -> dict[str, Any]:
    resp = client.get(
        f"/fantasy/teams/{seeded['fantasy_team_id']}/season/{seeded['season_id']}/breakdown"
    )
    assert resp.status_code == 200, resp.text
    return resp.json()


def test_the_drafted_race_is_the_plain_value(
    client: Client, seeded: dict[str, Any]
) -> None:
    assert breakdown(client, seeded)["race_breakdown"]["race"] == "HU"


def test_every_race_key_is_a_plain_value(
    client: Client, seeded: dict[str, Any]
) -> None:
    """all_race_points is keyed by race, and the page colours the chip
    whose key equals race_breakdown.race, so the keys and that value have
    to be written the same way."""
    race_breakdown = breakdown(client, seeded)["race_breakdown"]
    valid = {"RANDOM", "HU", "OC", "NE", "UD"}

    assert set(race_breakdown["all_race_points"]) <= valid
    assert race_breakdown["race"] in valid


def test_no_enum_repr_reaches_the_page(client: Client, seeded: dict[str, Any]) -> None:
    """Nothing anywhere in the body carries the repr."""
    assert "Race." not in json.dumps(breakdown(client, seeded))


def test_no_route_that_carries_a_race_writes_the_repr(
    client: Client, seeded: dict[str, Any]
) -> None:
    """The response models render the value, so only a body built by hand
    can carry the repr. These are the routes that carry a race."""
    team_id = seeded["fantasy_team_id"]
    season_id = seeded["season_id"]
    paths = [
        "/users",
        f"/users/{seeded['player_ids'][0]}",
        f"/teams/{seeded['team_a_id']}/seasons/{season_id}",
        f"/series/{seeded['series_played_id']}",
        "/fantasy/teams",
        f"/fantasy/teams/{team_id}",
        f"/fantasy/teams/{team_id}/season/{season_id}/breakdown",
    ]
    for path in paths:
        resp = client.get(path)
        assert resp.status_code == 200, (path, resp.status_code)
        assert "Race." not in resp.text, path
