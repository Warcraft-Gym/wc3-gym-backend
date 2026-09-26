"""The daily egress snapshot: its guard, the missing-extension answer and the window math."""

from datetime import datetime, timedelta

import pytest
from httpx2 import Client
from sqlalchemy import text

from app.core.db import Session
from app.models.egress_snapshot import EgressSnapshot, EgressStatement
from app.models.types import utcnow
from app.services import egress_snapshot

SECRET = "snapshot-secret"


@pytest.fixture
def scheduler(monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    monkeypatch.setenv("CRON_SECRET", SECRET)
    return {"Authorization": f"Bearer {SECRET}"}


def store(taken: datetime, counters: dict[int, tuple[int, int]]) -> None:
    """One snapshot: queryid -> (calls, rows), with a statement text per queryid."""
    with Session() as session:
        for queryid, (calls, rows) in counters.items():
            if session.get(EgressStatement, (queryid, 1)) is None:
                session.add(
                    EgressStatement(queryid=queryid, dbid=1, query=f"q{queryid}")
                )
            session.add(
                EgressSnapshot(
                    taken_at=taken, queryid=queryid, dbid=1, calls=calls, rows=rows
                )
            )
        session.commit()


@pytest.mark.parametrize("path", ["/jobs/egress-snapshot", "/jobs/egress-snapshots"])
def test_the_snapshot_routes_are_behind_the_scheduler_secret(
    client: Client, scheduler: dict[str, str], path: str
) -> None:
    assert client.get(path).status_code == 401
    assert (
        client.get(path, headers={"Authorization": "Bearer wrong"}).status_code == 401
    )


def test_without_pg_stat_statements_the_job_says_so(
    client: Client, scheduler: dict[str, str]
) -> None:
    with Session() as session:
        if session.get_bind().dialect.name == "postgresql":
            pytest.skip("the Postgres path is the capture test below")
    response = client.get("/jobs/egress-snapshot", headers=scheduler)
    assert response.status_code == 200
    body = response.json()
    assert body["available"] is False
    assert body["reason"]
    assert body["window"] is None


def test_a_window_counts_growth_resets_and_new_statements(
    client: Client, scheduler: dict[str, str]
) -> None:
    now = utcnow().replace(microsecond=0)
    t0, t1, t2 = now - timedelta(days=2), now - timedelta(days=1), now
    store(t0, {1: (10, 1_000_000), 2: (5, 500_000)})
    # 1 grew by 2 M rows; 2 went down, so it was reset and counts 200 k; 3 is new, 700 k in full
    store(t1, {1: (20, 3_000_000), 2: (2, 200_000), 3: (7, 700_000)})
    store(t2, {1: (21, 3_000_100), 3: (7, 700_000)})

    with Session() as session:
        first = egress_snapshot.summary(session, t0)
        found = egress_snapshot.summary(session, t1)
    assert first.window is None
    assert first.statements == 2

    window = found.window
    assert window is not None
    assert (window.start, window.end, window.hours) == (t0, t1, 24)
    assert (window.rows, window.calls) == (2_900_000, 19)
    # 2.9 M rows at 100 bytes a row over one day
    assert (window.estimated_mb, window.mb_per_day) == (290, 290)
    assert window.over_budget is True
    assert found.statements == 3
    assert [(s.query, s.rows) for s in found.top] == [
        ("q1", 2_000_000),
        ("q3", 700_000),
        ("q2", 200_000),
    ]

    response = client.get("/jobs/egress-snapshots?days=7", headers=scheduler)
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    days = response.json()
    assert [(d["rows"], d["calls"], d["over_budget"]) for d in days] == [
        (2_900_000, 19, True),
        (100, 1, False),
    ]


def test_the_capture_skips_its_own_statements_and_drops_old_snapshots(
    app: object,
) -> None:
    """Postgres only: a table named pg_stat_statements stands in for the extension's view."""
    with Session() as session:
        if session.get_bind().dialect.name != "postgresql":
            pytest.skip("the capture is an INSERT ... SELECT on Postgres")
        session.execute(
            text(
                "CREATE TABLE pg_stat_statements (queryid bigint, dbid oid, "
                "query text, calls bigint, rows bigint)"
            )
        )
        session.execute(
            text(
                "INSERT INTO pg_stat_statements VALUES "
                "(1, 5, 'SELECT   *\n FROM users', 3, 30), "
                "(1, 5, 'SELECT * FROM users', 1, 10), "
                "(2, 5, 'INSERT INTO egress_snapshot SELECT 1', 1, 4000), "
                "(NULL, 5, '<insufficient privilege>', 9, 90)"
            )
        )
        session.commit()
    store(utcnow() - timedelta(days=40), {7: (1, 1)})
    try:
        result = egress_snapshot.take()
        with Session() as session:
            texts = session.execute(
                text("SELECT queryid, query FROM egress_statement")
            ).all()
            kept = session.execute(
                text("SELECT queryid, calls, rows FROM egress_snapshot")
            ).all()
    finally:
        with Session() as session:
            session.execute(text("DROP TABLE pg_stat_statements"))
            session.commit()
    assert result.available is True
    assert result.statements == 1
    assert result.window is None
    assert [tuple(r) for r in texts] == [(1, "SELECT * FROM users")]
    assert [tuple(r) for r in kept] == [(1, 4, 40)]
