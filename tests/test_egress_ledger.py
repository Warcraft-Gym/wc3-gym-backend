"""Every request reports its database cost and adds it to the daily ledger."""

from typing import Any

import pytest
from httpx2 import Client

SECRET = "egress-secret"


@pytest.fixture
def scheduler(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    monkeypatch.setenv("CRON_SECRET", SECRET)
    return {"Authorization": f"Bearer {SECRET}"}


def test_a_list_route_reports_its_cost(client: Client, seeded: dict[str, Any]) -> None:
    response = client.get(f"/events/{seeded['season_id']}/series")
    assert response.status_code == 200
    assert int(response.headers["X-DB-Statements"]) > 0
    assert int(response.headers["X-DB-Rows"]) > 0
    assert int(response.headers["X-Response-Bytes"]) == len(response.content)


def test_the_ledger_counts_every_call(
    client: Client, seeded: dict[str, Any], scheduler: dict[str, str]
) -> None:
    for _ in range(3):
        client.get(f"/events/{seeded['season_id']}/series")
    client.get("/users")
    client.get("/no/such/path")

    response = client.get("/jobs/egress", headers=scheduler)
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    rows = {(row["route"], row["method"]): row for row in response.json()}
    assert set(rows) == {("/events/{event_id}/series", "GET"), ("/users", "GET")}
    series = rows[("/events/{event_id}/series", "GET")]
    assert series["calls"] == 3
    assert series["rows"] > 0
    assert series["bytes"] > 0
    assert rows[("/users", "GET")]["calls"] == 1

    # The read route itself is never recorded
    again = client.get("/jobs/egress", headers=scheduler).json()
    assert {row["route"] for row in again} == {"/events/{event_id}/series", "/users"}


def test_the_ledger_is_behind_the_scheduler_secret(
    client: Client, scheduler: dict[str, str]
) -> None:
    assert client.get("/jobs/egress").status_code == 401
