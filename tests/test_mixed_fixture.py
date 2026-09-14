"""The mixed fixture, the Altar of Champions Clan War, as ordered series.

One fixture of two clans holds five series in order: a drafted 1v1, a drafted
2v2, a 4v4 on any pick, a drafted 1v1 and a 1v1 on any pick. A captain names
the roster his side fields, a player plays one drafted series of the fixture,
and the fixture score sums the five.
"""

from collections.abc import Callable
from typing import Any

import pytest
from httpx2 import Client

from app.core.db import Session
from app.models.base import ident
from app.models.enums import EventKind, StageFormat
from app.models.event_stage import EventStage
from app.models.relationships import DBEventRound
from app.models.season import Season
from app.models.team import Team
from tests.test_stage_engine import players, score

# The Clan War rows, in the order the fixture plays them
CLAN_WAR = [
    {"side_size": 1, "pick_rule": "drafted"},
    {"side_size": 2, "pick_rule": "drafted"},
    {"side_size": 4, "pick_rule": "any"},
    {"side_size": 1, "pick_rule": "drafted"},
    {"side_size": 1, "pick_rule": "any"},
]


@pytest.fixture
def clan_war(
    client: Client, auth_headers: dict[str, str], member: Callable[..., dict[str, str]]
) -> dict[str, Any]:
    """Two clans of four, entered in one event, with one empty fixture.

    The rosters come back as the player ids and as the Discord ids their
    captains sign in with, so a test acts as either side.
    """
    ids = players(8)
    with Session.begin() as session:
        event = Season(
            name="Altar of Champions",
            kind=EventKind.cup,
            series_per_round=1,
            published=True,
        )
        session.add(event)
        session.flush()
        stage = EventStage(
            event_id=ident(event), position=1, format=StageFormat.gnl, best_of=3
        )
        teams = [Team(name="Clan A"), Team(name="Clan B")]
        session.add_all([stage, *teams])
        session.flush()
        session.add(
            DBEventRound(
                stage_id=ident(stage),
                season_id=ident(event),
                number=1,
                name="Round 1",
            )
        )
        event_id, stage_id = ident(event), ident(stage)
        team_ids = [ident(team) for team in teams]
    rosters = [ids[:4], ids[4:]]
    for place, (team_id, roster) in enumerate(zip(team_ids, rosters, strict=True)):
        base = f"/teams/{team_id}/seasons/{event_id}"
        added = client.post(
            f"{base}/players", json={"player_ids": roster}, headers=auth_headers
        )
        assert added.status_code == 200, added.text
        seated = client.put(
            f"{base}/captains", json={"captain_ids": roster[:1]}, headers=auth_headers
        )
        assert seated.status_code == 200, seated.text
        entered = client.post(
            f"/events/{event_id}/entrants",
            json={"team_id": team_id},
            headers=member(f"9{place * 4 + 1:04d}"),
        )
        assert entered.status_code == 201, entered.text
    fixture = client.post(
        "/matches",
        json={
            "team1_id": team_ids[0],
            "team2_id": team_ids[1],
            "season_id": event_id,
            "playday": 1,
        },
        headers=auth_headers,
    )
    assert fixture.status_code == 201, fixture.text
    return {
        "event": event_id,
        "stage": stage_id,
        "teams": team_ids,
        "rosters": rosters,
        "captains": ["90001", "90005"],
        "fixture": fixture.json()["id"],
    }


def template(client: Client, headers: dict[str, str], war: dict[str, Any]) -> Any:  # noqa: ANN401
    return client.post(
        f"/events/{war['event']}/stages/{war['stage']}"
        f"/fixtures/{war['fixture']}/template",
        json=CLAN_WAR,
        headers=headers,
    )


def roster(
    client: Client,
    headers: dict[str, str],
    series_id: int,
    side_no: int,
    user_ids: list[int],
) -> Any:  # noqa: ANN401
    return client.put(
        f"/series/{series_id}/sides",
        json={"sides": [{"side_no": side_no, "user_ids": user_ids}]},
        headers=headers,
    )


def written(client: Client, war: dict[str, Any]) -> list[dict[str, Any]]:
    """The series of the fixture, in the order the fixture plays them."""
    data = client.get(f"/events/{war['event']}/stages/{war['stage']}/series").json()
    return [row for row in data["series"] if row["match_id"] == war["fixture"]]


def test_the_template_writes_the_five_clan_war_series_in_order(
    client: Client, auth_headers: dict[str, str], clan_war: dict[str, Any]
) -> None:
    """Each row carries its sequence, its side size and its pick rule, and
    names the two team entrants the fixture pairs with no side written yet."""
    made = template(client, auth_headers, clan_war)

    assert made.status_code == 200, made.text
    rows = made.json()
    assert [row["sequence"] for row in rows] == [1, 2, 3, 4, 5]
    assert [row["side_size"] for row in rows] == [1, 2, 4, 1, 1]
    assert [row["pick_rule"] for row in rows] == [
        "drafted",
        "drafted",
        "any",
        "drafted",
        "any",
    ]
    assert all(row["sides"] == [] for row in rows)
    assert all(row["entrant1_id"] and row["entrant2_id"] for row in rows)
    # A series of the fixture plays the best-of its own stage names
    assert all(row["rules"]["best_of"] == 3 for row in rows)
    assert [row["sequence"] for row in written(client, clan_war)] == [1, 2, 3, 4, 5]


def test_a_fixture_that_already_holds_series_refuses_a_template(
    client: Client, auth_headers: dict[str, str], clan_war: dict[str, Any]
) -> None:
    assert template(client, auth_headers, clan_war).status_code == 200

    again = template(client, auth_headers, clan_war)

    assert again.status_code == 400, again.text
    assert again.json() == {"error": "This fixture already holds series"}


def test_a_captain_writes_the_roster_of_his_own_2v2_side(
    client: Client,
    auth_headers: dict[str, str],
    member: Callable[..., dict[str, str]],
    clan_war: dict[str, Any],
) -> None:
    """Two of the clan's four play the 2v2, and the other side is not his."""
    rows = template(client, auth_headers, clan_war).json()
    pair = rows[1]
    first, second = clan_war["rosters"]

    written_side = roster(
        client, member(clan_war["captains"][0]), pair["id"], 1, first[:2]
    )

    assert written_side.status_code == 200, written_side.text
    sides = written_side.json()["sides"]
    assert [side["side_no"] for side in sides] == [1, 1]
    assert {side["user_id"] for side in sides} == set(first[:2])
    # The other clan's captain writes the other side, and neither writes both
    other = roster(client, member(clan_war["captains"][1]), pair["id"], 2, second[:2])
    assert other.status_code == 200, other.text
    assert len(other.json()["sides"]) == 4
    crossed = roster(client, member(clan_war["captains"][0]), pair["id"], 2, second[2:])
    assert crossed.status_code == 403, crossed.text
    # A side fields as many players as the series names, from its own roster
    short = roster(client, auth_headers, pair["id"], 1, first[:1])
    assert short.status_code == 400, short.text
    stranger = roster(client, auth_headers, pair["id"], 1, [first[0], second[0]])
    assert stranger.status_code == 400, stranger.text


def test_a_player_plays_one_drafted_series_of_the_fixture(
    client: Client,
    auth_headers: dict[str, str],
    member: Callable[..., dict[str, str]],
    clan_war: dict[str, Any],
) -> None:
    """The draft tool refuses a pick a sibling drafted series already holds."""
    rows = template(client, auth_headers, clan_war).json()
    first, second = clan_war["rosters"]
    assert roster(client, auth_headers, rows[0]["id"], 1, first[:1]).status_code == 200
    assert roster(client, auth_headers, rows[0]["id"], 2, second[:1]).status_code == 200

    repeated = client.post(
        "/draft-series",
        json={
            "match_id": clan_war["fixture"],
            "player1_id": first[0],
            "player2_id": second[1],
            "host_player_id": first[0],
        },
        headers=member(clan_war["captains"][0]),
    )

    assert repeated.status_code == 400, repeated.text
    assert repeated.json() == {
        "error": "That player already plays a drafted series of this fixture"
    }
    # Two players the drafted series do not hold are drafted as they were
    fresh = client.post(
        "/draft-series",
        json={
            "match_id": clan_war["fixture"],
            "player1_id": first[1],
            "player2_id": second[1],
            "host_player_id": first[1],
        },
        headers=member(clan_war["captains"][0]),
    )
    assert fresh.status_code == 201, fresh.text
    # The roster write reads the same rule, so neither tool repeats a player
    twice = roster(client, auth_headers, rows[3]["id"], 1, first[:1])
    assert twice.status_code == 400, twice.text
    # The 4v4 picks freely, so it fields the whole clan the 1v1 drew from
    any_pick = roster(client, auth_headers, rows[2]["id"], 1, first)
    assert any_pick.status_code == 200, any_pick.text


def test_the_fixture_score_sums_its_five_series(
    client: Client, auth_headers: dict[str, str], clan_war: dict[str, Any]
) -> None:
    """Clan A takes three of the five 2-0 and Clan B takes two, and a clean
    win of a Bo3 pays 3, so the fixture stands at 9-6."""
    rows = template(client, auth_headers, clan_war).json()
    for place, row in enumerate(rows):
        first, secondly = (2, 0) if place < 3 else (0, 2)
        assert (
            score(client, auth_headers, row["id"], first, secondly).status_code == 200
        )

    fixture = client.get(f"/matches/{clan_war['fixture']}").json()

    assert (fixture["team1_score"], fixture["team2_score"]) == (9, 6)
    played = written(client, clan_war)
    assert [row["player1_points"] for row in played] == [3, 3, 3, 0, 0]
    assert [row["player2_points"] for row in played] == [0, 0, 0, 3, 3]
