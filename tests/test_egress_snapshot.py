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


def store(taken: datetime, counters: dict[tuple[int, int], tuple[int, int]]) -> None:
    """One snapshot: (queryid, userid) -> (calls, rows), with a statement text per queryid."""
    with Session() as session:
        for (queryid, userid), (calls, rows) in counters.items():
            if session.get(EgressStatement, (queryid, 1)) is None:
                session.add(
                    EgressStatement(queryid=queryid, dbid=1, query=f"q{queryid}")
                )
            session.flush()
            session.add(
                EgressSnapshot(
                    taken_at=taken,
                    queryid=queryid,
                    dbid=1,
                    userid=userid,
                    toplevel=True,
                    calls=calls,
                    rows=rows,
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
    store(
        t0, {(1, 10): (10, 1_000_000), (1, 20): (50, 5_000_000), (2, 10): (5, 500_000)}
    )
    # 1 grew by 2 M rows for role 10 and was reset for role 20, which counts its 100 alone;
    # 2 went down, so it was reset and counts 200 k; 3 is new, 700 k in full
    store(
        t1,
        {
            (1, 10): (20, 3_000_000),
            (1, 20): (1, 100),
            (2, 10): (2, 200_000),
            (3, 10): (7, 700_000),
        },
    )
    store(t2, {(1, 10): (21, 3_000_100), (3, 10): (7, 700_000)})

    with Session() as session:
        first = egress_snapshot.summary(session, t0)
        found = egress_snapshot.summary(session, t1)
    assert first.window is None
    assert first.statements == 3

    window = found.window
    assert window is not None
    assert (window.start, window.end, window.hours) == (t0, t1, 24)
    assert (window.rows, window.calls) == (2_900_100, 20)
    # 2.9 M rows at 100 bytes a row over one day
    assert (window.estimated_mb, window.mb_per_day) == (290, 290)
    assert window.over_budget is True
    assert found.statements == 4
    assert [(s.query, s.rows) for s in found.top] == [
        ("q1", 2_000_100),
        ("q3", 700_000),
        ("q2", 200_000),
    ]

    response = client.get("/jobs/egress-snapshots?days=7", headers=scheduler)
    assert response.status_code == 200
    assert response.headers["Cache-Control"] == "no-store"
    days = response.json()
    assert [(d["rows"], d["calls"], d["over_budget"]) for d in days] == [
        (2_900_100, 20, True),
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
                "CREATE TABLE pg_stat_statements (queryid bigint, dbid oid, userid oid, "
                "toplevel bool, query text, calls bigint, rows bigint)"
            )
        )
        session.execute(
            text(
                "INSERT INTO pg_stat_statements VALUES "
                "(1, 5, 10, true, 'SELECT   *\n FROM users', 3, 30), "
                "(1, 5, 11, true, 'SELECT * FROM users', 1, 10), "
                "(2, 5, 10, true, 'INSERT INTO egress_snapshot SELECT 1', 1, 4000), "
                "(3, 5, 10, true, 'INSERT INTO egress_ledger VALUES (1)', 9, 9), "
                "(NULL, 5, 10, true, '<insufficient privilege>', 9, 90)"
            )
        )
        session.commit()
    store(utcnow() - timedelta(days=40), {(7, 10): (1, 1)})
    try:
        result = egress_snapshot.take()
        with Session() as session:
            texts = session.execute(
                text("SELECT queryid, query FROM egress_statement")
            ).all()
            kept = session.execute(
                text(
                    "SELECT queryid, userid, calls, rows FROM egress_snapshot "
                    "ORDER BY userid"
                )
            ).all()
    finally:
        with Session() as session:
            session.execute(text("DROP TABLE pg_stat_statements"))
            session.commit()
    assert result.available is True
    assert result.statements == 2
    assert result.window is None
    assert [tuple(r) for r in texts] == [(1, "SELECT * FROM users")]
    # One row per role: no role's counter is summed into another's
    assert [tuple(r) for r in kept] == [(1, 10, 3, 30), (1, 11, 1, 10)]


def test_a_run_within_an_hour_of_the_last_writes_nothing(
    client: Client, scheduler: dict[str, str]
) -> None:
    """A retry or a manual call would divide a short window into a false day rate."""
    store(utcnow() - timedelta(minutes=10), {(1, 10): (1, 1)})
    response = client.get("/jobs/egress-snapshot", headers=scheduler)
    assert response.status_code == 200
    body = response.json()
    assert body["available"] is True
    assert body["skipped"] == "last snapshot 10 min ago"
    assert body["window"] is None
    with Session() as session:
        assert (
            session.execute(text("SELECT count(*) FROM egress_snapshot")).scalar_one()
            == 1
        )


def result(
    mb_per_day: float, available: bool = True
) -> egress_snapshot.EgressSnapshotResult:
    start = datetime(2026, 9, 26)
    w = egress_snapshot.window(
        start, start + timedelta(days=1), 10, int(mb_per_day * 1e4)
    )
    return egress_snapshot.EgressSnapshotResult(
        available=available,
        reason=None
        if available
        else "the pg_stat_statements extension is not installed",
        budget_mb_per_day=egress_snapshot.BUDGET_MB_PER_DAY,
        window=w if available else None,
        top=[
            egress_snapshot.EgressStatementRows(query="SELECT series", calls=10, rows=5)
        ],
    )


def test_the_alert_names_an_over_budget_day_or_a_failed_run_and_nothing_else() -> None:
    assert egress_snapshot.alert_text(result(50)) is None
    over = egress_snapshot.alert_text(result(140))
    assert (
        over is not None
        and "~140 MB/day (budget 80)" in over
        and "SELECT series" in over
    )
    assert egress_snapshot.alert_text(result(0, available=False)) == (
        "Egress snapshot could not run: the pg_stat_statements extension is not installed"
    )


def test_the_alert_posts_only_when_the_webhook_is_set(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    posts: list[dict] = []

    class Sent:
        def raise_for_status(self) -> None: ...

    def post(url: str, json: dict, timeout: float) -> Sent:
        posts.append(json)
        return Sent()

    monkeypatch.setattr(egress_snapshot.requests, "post", post)
    monkeypatch.delenv("DEV_ALERTS_WEBHOOK_URL", raising=False)
    egress_snapshot.alert(result(140))
    monkeypatch.setenv("DEV_ALERTS_WEBHOOK_URL", "")
    egress_snapshot.alert(result(140))
    assert posts == []

    monkeypatch.setenv("DEV_ALERTS_WEBHOOK_URL", "https://discord.test/webhook")
    egress_snapshot.alert(result(50))
    egress_snapshot.alert(result(140))
    assert len(posts) == 1 and posts[0]["allowed_mentions"] == {"parse": []}

    def down(url: str, json: dict, timeout: float) -> Sent:
        raise egress_snapshot.requests.ConnectionError("down")

    monkeypatch.setattr(egress_snapshot.requests, "post", down)
    egress_snapshot.alert(result(140))


def test_a_failed_post_logs_no_webhook_token(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    url = "https://discord.test/api/webhooks/1/SECRETTOKEN"
    monkeypatch.setenv("DEV_ALERTS_WEBHOOK_URL", url)

    def down(url: str, json: dict, timeout: float) -> None:
        raise egress_snapshot.requests.ConnectionError(
            f"Max retries exceeded with url: {url}"
        )

    monkeypatch.setattr(egress_snapshot.requests, "post", down)
    egress_snapshot.alert(result(140))
    assert "ConnectionError" in caplog.text and "SECRETTOKEN" not in caplog.text


def test_a_crashed_run_posts_its_error_and_still_fails(
    client: Client, scheduler: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    sent: list[egress_snapshot.EgressSnapshotResult] = []

    def crash() -> None:
        raise RuntimeError("connection lost")

    monkeypatch.setattr(egress_snapshot, "take", crash)
    monkeypatch.setattr(egress_snapshot, "alert", sent.append)
    assert client.get("/jobs/egress-snapshot", headers=scheduler).status_code == 500
    assert [r.reason for r in sent] == ["RuntimeError"]
