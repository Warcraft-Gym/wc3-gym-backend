"""The season achievements page: what a season pays, at what numbers.

The catalogue is code. A season's set is rows that name a rule, a price and
the numbers the rule reads; the page replaces the set in one PUT.
"""

from datetime import timedelta
from typing import Any

import pytest
from httpx2 import Client
from sqlalchemy import select
from sqlmodel import col

from app.core.achievements import ALL_PAID, BY_ID, HAT_TRICK, TEAM_IDS
from app.core.db import Session
from app.models.ladder_achievement import LadderAchievement
from tests.test_ladder_read import INSIDE, add_match, ladder_of, player_of, sign_up

HAT_TRICK_ROW = {"rule_id": "hat_trick", "points": 5, "params": {"wins": 2}}
FULL_ROSTER_ROW = {"rule_id": "full_roster", "points": 30, "params": {}}


def test_the_catalogue_lists_every_rule_with_its_numbers(client: Client) -> None:
    resp = client.get("/achievements")
    assert resp.status_code == 200, resp.text
    rules = {rule["rule_id"]: rule for rule in resp.json()}

    assert rules.keys() == BY_ID.keys()
    assert rules["hat_trick"] == {
        "rule_id": "hat_trick",
        "name": HAT_TRICK.name,
        "description": "Win {wins} games in a row",
        "icon": HAT_TRICK.icon,
        "team": False,
        "points": HAT_TRICK.points,
        "params": {"wins": 3},
    }
    assert rules["full_roster"]["team"] is True
    assert {rule_id for rule_id, rule in rules.items() if rule["team"]} == TEAM_IDS


def test_a_season_answers_its_rows_in_catalogue_order(
    client: Client, seeded: dict[str, Any]
) -> None:
    resp = client.get(f"/seasons/{seeded['season_id']}/achievements")
    assert resp.status_code == 200, resp.text
    rows = resp.json()

    assert [row["rule_id"] for row in rows] == list(BY_ID)
    assert {row["rule_id"]: row["points"] for row in rows} == ALL_PAID
    assert client.get("/seasons/999/achievements").status_code == 404


def test_the_put_replaces_the_set_and_stores_only_the_overrides(
    client: Client, seeded: dict[str, Any], auth_headers: dict[str, str]
) -> None:
    season_id = seeded["season_id"]
    resp = client.put(
        f"/seasons/{season_id}/achievements",
        json=[HAT_TRICK_ROW, FULL_ROSTER_ROW],
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    assert [(row["rule_id"], row["points"], row["params"]) for row in resp.json()] == [
        ("hat_trick", 5, {"wins": 2}),
        ("full_roster", 30, {"games": 10}),
    ]
    assert client.get(f"/seasons/{season_id}/achievements").json() == resp.json()

    with Session() as session:
        stored = session.scalars(
            select(LadderAchievement).where(
                col(LadderAchievement.season_id) == season_id
            )
        ).all()
    assert {row.rule_id: row.params for row in stored} == {
        "hat_trick": {"wins": 2},
        "full_roster": {},
    }

    # A number equal to the default stores nothing, so the row follows the code
    resp = client.put(
        f"/seasons/{season_id}/achievements",
        json=[{"rule_id": "hat_trick", "points": 5, "params": {"wins": 3}}],
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text
    with Session() as session:
        stored = session.scalars(select(LadderAchievement)).all()
    assert [(row.rule_id, row.params) for row in stored] == [("hat_trick", {})]


@pytest.mark.parametrize(
    ("body", "status", "message"),
    [
        ([{"rule_id": "no_such_rule", "points": 1}], 422, "No rule no_such_rule"),
        (
            [{"rule_id": "hat_trick", "points": 1, "params": {"games": 4}}],
            422,
            "hat_trick reads no games",
        ),
        ([{"rule_id": "hat_trick", "points": -1}], 422, "greater than or equal to 0"),
        (
            [{"rule_id": "hat_trick", "points": 1, "params": {"wins": 0}}],
            422,
            "greater than or equal to 1",
        ),
        ([HAT_TRICK_ROW, HAT_TRICK_ROW], 400, "A rule is listed twice"),
    ],
)
def test_the_put_rejects_a_row_the_rule_cannot_read(
    client: Client,
    seeded: dict[str, Any],
    auth_headers: dict[str, str],
    body: list[dict[str, Any]],
    status: int,
    message: str,
) -> None:
    resp = client.put(
        f"/seasons/{seeded['season_id']}/achievements",
        json=body,
        headers=auth_headers,
    )
    assert resp.status_code == status, resp.text
    assert message in resp.text
    # Nothing changed
    assert len(
        client.get(f"/seasons/{seeded['season_id']}/achievements").json()
    ) == len(ALL_PAID)


def test_the_put_needs_an_admin(client: Client, seeded: dict[str, Any]) -> None:
    resp = client.put(f"/seasons/{seeded['season_id']}/achievements", json=[])
    assert resp.status_code == 401, resp.text


def test_a_season_number_changes_who_earns_the_badge(
    client: Client, seeded: dict[str, Any], auth_headers: dict[str, str]
) -> None:
    """Two wins in a row are no hat-trick at the default, and one at wins=2."""
    season_id, player = seeded["season_id"], seeded["player_ids"][0]
    sign_up(season_id, [player])
    add_match(player, "one", INSIDE)
    add_match(player, "two", INSIDE + timedelta(hours=1))

    def earned() -> set[str]:
        body = ladder_of(client, auth_headers, season_id)
        return {badge["id"] for badge in player_of(body, player)["achievements"]}

    def rule_text() -> str:
        body = ladder_of(client, auth_headers, season_id)
        rule = next(r for r in body["achievement_rules"] if r["id"] == "hat_trick")
        return rule["description"]

    assert "hat_trick" not in earned()
    assert rule_text() == "Win 3 games in a row"

    resp = client.put(
        f"/seasons/{season_id}/achievements",
        json=[HAT_TRICK_ROW],
        headers=auth_headers,
    )
    assert resp.status_code == 200, resp.text

    assert earned() == {"hat_trick"}
    assert rule_text() == "Win 2 games in a row"
    body = ladder_of(client, auth_headers, season_id)
    badge = player_of(body, player)["achievements"][0]
    assert (badge["points"], badge["description"]) == (5, "Win 2 games in a row")
