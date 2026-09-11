"""A draft holds map scores inside a Bo3, so promoting it never fails on them."""

from typing import Any

import pytest
from httpx2 import Client

from tests.test_draft_permissions import draft_body


@pytest.mark.parametrize("score", [3, -1])
def test_a_draft_score_outside_a_bo3_is_refused(
    client: Client,
    seeded: dict[str, Any],
    auth_headers: dict[str, str],
    score: int,
) -> None:
    body = {**draft_body(seeded), "player1_score": score, "player2_score": 0}
    resp = client.post("/draft-series", json=body, headers=auth_headers)
    assert resp.status_code == 422, resp.text

    resp = client.post("/draft-series", json=draft_body(seeded), headers=auth_headers)
    assert resp.status_code == 201, resp.text
    resp = client.put(
        f"/draft-series/{resp.json()['id']}",
        json={"player2_score": score},
        headers=auth_headers,
    )
    assert resp.status_code == 422, resp.text


def test_a_scored_draft_promotes(
    client: Client, seeded: dict[str, Any], auth_headers: dict[str, str]
) -> None:
    body = {
        **draft_body(seeded),
        "player2_id": seeded["player_ids"][3],
        "player1_score": 2,
        "player2_score": 1,
    }
    resp = client.post("/draft-series", json=body, headers=auth_headers)
    assert resp.status_code == 201, resp.text

    resp = client.post(
        f"/draft-series/{resp.json()['id']}/promote", headers=auth_headers
    )
    assert resp.status_code == 201, resp.text
    assert (resp.json()["player1_score"], resp.json()["player2_score"]) == (2, 1)
