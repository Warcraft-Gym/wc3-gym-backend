"""The egress monitor: the cycle's level, the posts per change of level and the payload rules."""

import json
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace
from typing import Any, Self

import pytest
from httpx2 import Client
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError

from app.core.db import Session
from app.models.egress_ledger import EgressLedger
from app.models.egress_snapshot import EgressWindow
from app.models.monitor_state import MonitorState
from app.services import egress_monitor, egress_snapshot
from app.services.egress_monitor import Level
from tests.test_egress_snapshot import store

SECRET = "monitor-secret"
FAKE_ID = "123456789012345678"
# A run on day 4 of the cycle that started 26 Sep 2026
NOW = datetime(2026, 9, 29, 0, 30, tzinfo=UTC)


def w(end: datetime, mb: float, hours: float = 24) -> EgressWindow:
    """A window of `mb` estimated MB ending at `end`; 100 bytes a row is 10,000 rows a MB."""
    return egress_snapshot.window(end - timedelta(hours=hours), end, 10, int(mb * 1e4))


def daily(mb: float, days: int = 3, now: datetime = NOW) -> list[EgressWindow]:
    """One window a day ending at `now` and the days before it."""
    return [w(now - timedelta(days=d), mb) for d in reversed(range(days))]


@pytest.fixture
def sent(monkeypatch: pytest.MonkeyPatch) -> list[dict[str, Any]]:
    """The payloads the webhook would receive."""
    posts: list[dict[str, Any]] = []

    class Sent:
        def raise_for_status(self) -> None: ...

    def post(url: str, json: dict[str, Any], timeout: float) -> Sent:
        posts.append(json)
        return Sent()

    monkeypatch.setattr(egress_monitor.requests, "post", post)
    # The database size is read only on Postgres: None keeps the posts the same on both
    monkeypatch.setattr(egress_monitor, "database_mb", lambda: None)
    monkeypatch.setenv("DEV_ALERTS_WEBHOOK_URL", "https://discord.test/webhook")
    for name in (
        "DEV_ALERTS_MENTION_USER_ID",
        "VERCEL_USAGE_TOKEN",
        "VERCEL_TEAM_ID",
        *egress_monitor.DASHBOARDS.values(),
    ):
        monkeypatch.delenv(name, raising=False)
    return posts


def run(
    monkeypatch: pytest.MonkeyPatch, found: list[EgressWindow], now: datetime = NOW
) -> None:
    """One successful run that reads `found` as its windows."""
    monkeypatch.setattr(egress_monitor, "windows", lambda session, since: found)
    result = egress_snapshot.EgressSnapshotResult(
        available=True,
        budget_mb_per_day=egress_snapshot.BUDGET_MB_PER_DAY,
        window=found[-1] if found else None,
    )
    egress_monitor.report(result, now)


def state(key: str = egress_monitor.KEY) -> MonitorState | None:
    with Session() as session:
        return session.get(MonitorState, key)


def titles(posts: list[dict[str, Any]]) -> list[str]:
    return [p["embeds"][0]["title"] for p in posts]


def size(payload: dict[str, Any]) -> int:
    e = payload["embeds"][0]
    return (
        len(e["title"])
        + len(e["description"])
        + len(e["footer"]["text"])
        + sum(len(f["name"]) + len(f["value"]) for f in e["fields"])
    )


def test_the_cycle_starts_on_day_26_utc() -> None:
    before = egress_monitor.cycle(datetime(2026, 9, 25, 23, 59, tzinfo=UTC))
    assert (before.start, before.end, before.days) == (
        datetime(2026, 8, 26, tzinfo=UTC),
        datetime(2026, 9, 26, tzinfo=UTC),
        31,
    )
    on = egress_monitor.cycle(datetime(2026, 9, 26, tzinfo=UTC))
    assert (on.start.date(), on.end.date(), on.days) == (
        date(2026, 9, 26),
        date(2026, 10, 26),
        30,
    )
    january = egress_monitor.cycle(datetime(2027, 1, 10, tzinfo=UTC))
    assert (january.start.date(), january.end.date()) == (
        date(2026, 12, 26),
        date(2027, 1, 26),
    )


def test_the_projection_extends_the_3_day_average_over_the_days_left() -> None:
    m = egress_monitor.meters(daily(200), NOW)
    assert m.cycle_mb == 600
    assert m.average_mb_per_day == pytest.approx(200)
    left = (datetime(2026, 10, 26, tzinfo=UTC) - NOW).total_seconds() / 86400
    assert m.projected_mb == pytest.approx(600 + 200 * left)
    assert m.day == 4
    assert m.level == Level.RED


def test_the_run_after_day_26_counts_the_day_before_in_the_old_cycle() -> None:
    """The 00:00 run on the 26th covers the 25th, which the cycle before pays for."""
    now = datetime(2026, 9, 27, 0, 10, tzinfo=UTC)
    found = [w(datetime(2026, 9, 26, 0, 10, tzinfo=UTC), 900), w(now, 60)]
    m = egress_monitor.meters(found, now)
    assert m.cycle_mb == 60
    # Both windows ended in the last 72 hours: 960 MB over 48 hours
    assert m.average_mb_per_day == pytest.approx(480)
    assert m.covers == date(2026, 9, 26)


def test_with_no_window_in_the_last_72_hours_the_last_window_sets_the_rate() -> None:
    m = egress_monitor.meters([w(NOW - timedelta(days=5), 30, hours=12)], NOW)
    assert m.average_mb_per_day == pytest.approx(60)


@pytest.mark.parametrize(
    ("found", "level"),
    [
        (daily(50), Level.NORMAL),
        # 120 MB yesterday is over the daily budget; the cycle stays far under the cap
        (daily(50, 2) + [w(NOW, 120)], Level.AMBER),
        (daily(200), Level.RED),
        ([], Level.NORMAL),
    ],
)
def test_the_level(found: list[EgressWindow], level: Level) -> None:
    assert egress_monitor.meters(found, NOW).level == level


def test_normal_to_red_alerts_then_red_again_posts_only_the_digest(
    monkeypatch: pytest.MonkeyPatch, sent: list[dict[str, Any]]
) -> None:
    before = NOW - timedelta(days=1)
    run(monkeypatch, daily(50, now=before), before)
    assert titles(sent) == ["Daily infrastructure digest · 27 Sep"]
    assert sent[0]["flags"] == egress_monitor.SILENT
    assert sent[0]["embeds"][0]["color"] == egress_monitor.BLUE
    sent.clear()

    run(monkeypatch, daily(200))
    assert titles(sent) == [
        "Supabase egress: on track to pass the 5 GB cap",
        "Daily infrastructure digest · 28 Sep",
    ]
    alert, digest = sent
    assert "flags" not in alert
    assert digest["flags"] == egress_monitor.SILENT
    assert digest["embeds"][0]["color"] == egress_monitor.RED
    current = state()
    assert current is not None and (current.level, current.since) == (
        "red",
        NOW - timedelta(days=1),
    )
    sent.clear()

    after = NOW + timedelta(days=1)
    run(monkeypatch, daily(200, now=after), after)
    assert titles(sent) == ["Daily infrastructure digest · 29 Sep"]
    current = state()
    assert current is not None and current.since == NOW - timedelta(days=1)


def test_red_to_normal_posts_a_silent_recovery_then_the_digest(
    monkeypatch: pytest.MonkeyPatch, sent: list[dict[str, Any]]
) -> None:
    before = NOW - timedelta(days=3)
    run(monkeypatch, daily(200, now=before), before)
    sent.clear()
    run(monkeypatch, daily(20))
    assert titles(sent) == [
        "Supabase egress: back on track for the 5 GB cap",
        "Daily infrastructure digest · 28 Sep",
    ]
    recovery = sent[0]
    assert recovery["flags"] == egress_monitor.SILENT
    assert recovery["embeds"][0]["color"] == egress_monitor.GREEN
    assert recovery["embeds"][0]["fields"][2]["name"] == "Red for"
    assert recovery["embeds"][0]["fields"][2]["value"].startswith("4 days, since <t:")


def test_amber_colours_the_digest_and_never_alerts(
    monkeypatch: pytest.MonkeyPatch, sent: list[dict[str, Any]]
) -> None:
    run(monkeypatch, daily(50, 2) + [w(NOW, 120)])
    assert titles(sent) == ["Daily infrastructure digest · 28 Sep"]
    embed = sent[0]["embeds"][0]
    assert embed["color"] == egress_monitor.AMBER
    assert embed["description"] == "Yesterday was over the daily budget."


def test_an_unavailable_run_alerts_once_and_a_good_run_says_it_runs_again(
    monkeypatch: pytest.MonkeyPatch, sent: list[dict[str, Any]]
) -> None:
    failed = egress_snapshot.unavailable(
        "the pg_stat_statements extension is not installed"
    )
    egress_monitor.report(failed, NOW - timedelta(hours=5))
    egress_monitor.report(failed, NOW - timedelta(hours=4))
    assert titles(sent) == ["Egress snapshot could not run"]
    assert sent[0]["embeds"][0]["description"].startswith(
        "The pg_stat_statements extension is not installed."
    )
    sent.clear()

    run(monkeypatch, [])
    assert titles(sent) == [
        "Egress snapshot: running again",
        "Daily infrastructure digest · 29 Sep",
    ]
    assert sent[1]["embeds"][0]["description"] == (
        "Baseline taken. First figures after the next run."
    )
    assert sent[0]["embeds"][0]["fields"][2]["value"].startswith("5 hours, since")


def test_a_skipped_run_posts_nothing_and_keeps_the_level(
    sent: list[dict[str, Any]],
) -> None:
    skipped = egress_snapshot.EgressSnapshotResult(
        available=True, skipped="last snapshot 10 min ago", budget_mb_per_day=80
    )
    egress_monitor.report(skipped, NOW)
    assert sent == []
    assert state() is None


def test_only_an_alert_tags_the_user_and_only_a_digit_id(
    monkeypatch: pytest.MonkeyPatch, sent: list[dict[str, Any]]
) -> None:
    monkeypatch.setenv("DEV_ALERTS_MENTION_USER_ID", f" {FAKE_ID} ")
    run(monkeypatch, daily(200))
    alert, digest = sent
    assert alert["content"] == f"<@{FAKE_ID}> egress needs action today"
    assert alert["allowed_mentions"] == {"users": [FAKE_ID]}
    assert "content" not in digest and digest["allowed_mentions"] == {"parse": []}

    monkeypatch.setenv("DEV_ALERTS_MENTION_USER_ID", "<@123>")
    payload = egress_monitor.unavailable_alert("down", NOW, egress_monitor.mention_id())
    assert "content" not in payload and payload["allowed_mentions"] == {"parse": []}


def test_nothing_is_sent_without_the_webhook(
    monkeypatch: pytest.MonkeyPatch, sent: list[dict[str, Any]]
) -> None:
    monkeypatch.delenv("DEV_ALERTS_WEBHOOK_URL")
    run(monkeypatch, daily(200))
    monkeypatch.setenv("DEV_ALERTS_WEBHOOK_URL", "")
    egress_monitor.post(egress_monitor.unavailable_alert("down", NOW, None))
    assert sent == []


def test_the_routes_are_yesterdays_top_three_by_rows(
    monkeypatch: pytest.MonkeyPatch, sent: list[dict[str, Any]]
) -> None:
    yesterday = (NOW - timedelta(days=1)).date()
    with Session() as session:
        for day, route, rows in [
            (yesterday, "/events/{event_id}/series", 2_260_000),
            (yesterday, "/stats/career", 1_300_000),
            (yesterday, "/users/{key}", 58_877),
            (yesterday, "/maps", 12),
            (NOW.date(), "/teams", 9_000_000),
        ]:
            session.add(
                EgressLedger(
                    day=day,
                    route=route,
                    method="GET",
                    calls=10_675,
                    statements=1,
                    rows=rows,
                    bytes=0,
                )
            )
        session.commit()
    run(monkeypatch, daily(200))
    routes = sent[0]["embeds"][0]["fields"][6]
    assert routes["name"] == "Top routes (rows)"
    assert routes["value"].splitlines() == [
        "`GET /events/{event_id}/series` 2,260,000 rows · 10,675 calls",
        "`GET /stats/career` 1,300,000 rows · 10,675 calls",
        "`GET /users/{key}` 58,877 rows · 10,675 calls",
    ]


def test_every_payload_fits_discords_limits() -> None:
    long = [
        EgressLedger(
            day=NOW.date(),
            route="/" + "x" * 2000,
            method="GET",
            calls=1,
            statements=1,
            rows=1,
            bytes=0,
        )
    ] * 3
    m = egress_monitor.meters(daily(20_000), NOW)
    links = {
        "Supabase usage": "https://supabase.test/usage",
        "Vercel usage": "https://vercel.test/usage",
    }
    alert = egress_monitor.alert(m, long, NOW, FAKE_ID, links)
    assert alert["embeds"][0]["title"] == "Supabase egress: over the 5 GB cap"
    digest = egress_monitor.digest(m, long, links, 499.0)
    for payload, footer in [
        (alert, egress_monitor.FOOTER),
        (digest, egress_monitor.DIGEST_FOOTER),
        (egress_monitor.recovery(m, "red", NOW), egress_monitor.FOOTER),
        (
            egress_monitor.unavailable_alert("x" * 5000, NOW, None),
            egress_monitor.FOOTER,
        ),
        (
            egress_monitor.db_alert(499.0, NOW, FAKE_ID, links),
            egress_monitor.MONITOR_FOOTER,
        ),
        (egress_monitor.db_recovery(10.0, NOW, NOW), egress_monitor.MONITOR_FOOTER),
    ]:
        embed = payload["embeds"][0]
        assert size(payload) <= 6000
        assert len(embed["title"]) <= 256 and len(embed["description"]) <= 4096
        assert len(embed["fields"]) <= 25
        assert all(len(f["value"]) <= 1024 for f in embed["fields"])
        assert embed["footer"]["text"] == footer
        assert embed["timestamp"] == NOW.isoformat()
        assert FAKE_ID not in json.dumps(embed)


def test_a_failed_post_logs_no_webhook_token(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    url = "https://discord.test/api/webhooks/1/SECRETTOKEN"
    monkeypatch.setenv("DEV_ALERTS_WEBHOOK_URL", url)

    def down(url: str, json: dict[str, Any], timeout: float) -> None:
        raise egress_monitor.requests.ConnectionError(
            f"Max retries exceeded with url: {url}"
        )

    monkeypatch.setattr(egress_monitor.requests, "post", down)
    egress_monitor.post(egress_monitor.unavailable_alert("down", NOW, None))
    assert "ConnectionError" in caplog.text and "SECRETTOKEN" not in caplog.text


def test_a_crashed_run_alerts_once_and_still_fails(
    client: Client, monkeypatch: pytest.MonkeyPatch, sent: list[dict[str, Any]]
) -> None:
    monkeypatch.setenv("CRON_SECRET", SECRET)
    headers = {"Authorization": f"Bearer {SECRET}"}

    def crash() -> None:
        raise RuntimeError("connection lost")

    monkeypatch.setattr(egress_snapshot, "take", crash)
    assert client.get("/jobs/egress-snapshot", headers=headers).status_code == 500
    assert client.get("/jobs/egress-snapshot", headers=headers).status_code == 500
    assert titles(sent) == ["Egress snapshot could not run"]
    assert sent[0]["embeds"][0]["description"].startswith("RuntimeError.")


def test_a_crash_with_the_database_down_still_alerts(
    monkeypatch: pytest.MonkeyPatch, sent: list[dict[str, Any]]
) -> None:
    def down(result: object, now: object) -> None:
        raise RuntimeError("no database")

    monkeypatch.setattr(egress_monitor, "report", down)
    egress_monitor.crashed("OperationalError", NOW)
    assert titles(sent) == ["Egress snapshot could not run"]


def test_a_run_reads_its_windows_from_the_stored_snapshots(
    sent: list[dict[str, Any]],
) -> None:
    """No stand-in windows: two snapshots a day apart, 2 M rows between them, 200 MB."""
    store(NOW - timedelta(days=1), {(1, 10): (1, 0)})
    store(NOW, {(1, 10): (9, 2_000_000)})
    with Session() as session:
        taken = egress_snapshot.summary(session, NOW)
    egress_monitor.report(taken, NOW)
    assert titles(sent)[0] == "Supabase egress: on track to pass the 5 GB cap"
    fields = {f["name"]: f["value"] for f in sent[0]["embeds"][0]["fields"]}
    assert fields["Last window"] == "~200 MB/day"
    assert fields["Cycle so far"].endswith("0.2 GB of 5 GB")


def test_an_undelivered_alert_keeps_the_level_so_the_next_run_retries(
    monkeypatch: pytest.MonkeyPatch, sent: list[dict[str, Any]]
) -> None:
    before = NOW - timedelta(days=1)
    run(monkeypatch, daily(50, now=before), before)
    sent.clear()

    def down(url: str, timeout: float, **kwargs: object) -> None:
        raise egress_monitor.requests.ConnectionError("down")

    with monkeypatch.context() as broken:
        broken.setattr(egress_monitor.requests, "post", down)
        run(monkeypatch, daily(200))
    current = state()
    assert current is not None and current.level == "normal"

    monkeypatch.delenv("DEV_ALERTS_WEBHOOK_URL")
    run(monkeypatch, daily(200))
    current = state()
    assert current is not None and current.level == "normal"

    monkeypatch.setenv("DEV_ALERTS_WEBHOOK_URL", "https://discord.test/webhook")
    run(monkeypatch, daily(200))
    assert titles(sent)[0] == "Supabase egress: on track to pass the 5 GB cap"
    current = state()
    assert current is not None and current.level == "red"


def test_the_alert_shows_when_the_window_that_turned_it_red_began(
    monkeypatch: pytest.MonkeyPatch, sent: list[dict[str, Any]]
) -> None:
    run(monkeypatch, daily(200))
    fields = {f["name"]: f["value"] for f in sent[0]["embeds"][0]["fields"]}
    start = NOW - timedelta(days=1)
    assert fields["Since"] == f"<t:{int(start.timestamp())}:f>"


def test_fields_over_the_total_lose_the_trailing_ones() -> None:
    fields = [egress_monitor.field(f"f{i}", "x" * 1024) for i in range(10)]
    payload = egress_monitor.message(NOW, egress_monitor.BLUE, "t", "d", fields)
    embed = payload["embeds"][0]
    assert size(payload) <= 6000
    assert 1 <= len(embed["fields"]) < 10
    assert [f["name"] for f in embed["fields"]] == [
        f"f{i}" for i in range(len(embed["fields"]))
    ]


def test_a_monitor_failure_still_answers_the_snapshot(
    client: Client, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("CRON_SECRET", SECRET)

    def broken(result: object) -> None:
        raise RuntimeError("monitor down")

    monkeypatch.setattr(egress_monitor, "report", broken)
    response = client.get(
        "/jobs/egress-snapshot", headers={"Authorization": f"Bearer {SECRET}"}
    )
    assert response.status_code == 200
    assert "RuntimeError" in caplog.text


def test_the_posts_link_the_dashboards_that_are_set_to_https(
    monkeypatch: pytest.MonkeyPatch, sent: list[dict[str, Any]]
) -> None:
    before = NOW - timedelta(days=1)
    run(monkeypatch, daily(20, now=before), before)
    for payload in sent:
        embed = payload["embeds"][0]
        assert "url" not in embed
        assert "Dashboards" not in [f["name"] for f in embed["fields"]]
    sent.clear()

    monkeypatch.setenv("DEV_ALERTS_SUPABASE_USAGE_URL", "https://supabase.test/usage")
    monkeypatch.setenv("DEV_ALERTS_VERCEL_USAGE_URL", "http://vercel.test/usage")
    run(monkeypatch, daily(200))
    assert titles(sent) == [
        "Supabase egress: on track to pass the 5 GB cap",
        "Daily infrastructure digest · 28 Sep",
    ]
    for payload in sent:
        embed = payload["embeds"][0]
        assert embed["url"] == "https://supabase.test/usage"
        assert embed["fields"][-1] == {
            "name": "Dashboards",
            "value": "[Supabase usage](https://supabase.test/usage)",
            "inline": False,
        }
    alert_fields = [f["name"] for f in sent[0]["embeds"][0]["fields"]]
    assert alert_fields[-2:] == ["Next step", "Dashboards"]
    sent.clear()

    monkeypatch.setenv("DEV_ALERTS_VERCEL_USAGE_URL", "https://vercel.test/usage")
    monkeypatch.setenv("DEV_ALERTS_SUPABASE_USAGE_URL", "supabase.test/usage")
    run(monkeypatch, daily(200))
    embed = sent[0]["embeds"][0]
    assert "url" not in embed
    assert embed["fields"][-1]["value"] == "[Vercel usage](https://vercel.test/usage)"


def sized(monkeypatch: pytest.MonkeyPatch, mb: float | None) -> None:
    monkeypatch.setattr(egress_monitor, "database_mb", lambda: mb)


def test_the_database_size_is_read_on_the_server_in_one_row(app: object) -> None:
    with Session() as session:
        if session.get_bind().dialect.name != "postgresql":
            pytest.skip("pg_database_size is Postgres only")
        total = session.execute(
            text(
                "SELECT sum(pg_database_size(datname)) FROM pg_database "
                "WHERE NOT datistemplate"
            )
        ).scalar_one()
    mb = egress_monitor.database_mb()
    assert mb is not None and mb > 0
    # The size moves as the test database is written; a MB either way is the same read
    assert mb == pytest.approx(int(total) / (1024 * 1024), abs=1)


def test_on_sqlite_the_size_is_skipped(app: object) -> None:
    with Session() as session:
        if session.get_bind().dialect.name != "sqlite":
            pytest.skip("the SQLite path")
    assert egress_monitor.database_mb() is None


def test_the_digest_shows_the_database_size_when_it_was_read(
    monkeypatch: pytest.MonkeyPatch, sent: list[dict[str, Any]]
) -> None:
    sized(monkeypatch, 123.4)
    run(monkeypatch, daily(20))
    fields = {f["name"]: f for f in sent[0]["embeds"][0]["fields"]}
    assert fields["Database size"] == {
        "name": "Database size",
        "value": "~123 MB of the 500 MB cap\n`▰▰▱▱▱▱▱▱▱▱` 25%",
        "inline": True,
    }
    assert sent[0]["embeds"][0]["description"] == "All meters normal."
    assert state(egress_monitor.DB_KEY) is not None
    sent.clear()

    sized(monkeypatch, None)
    run(monkeypatch, daily(20))
    assert "Database size" not in [f["name"] for f in sent[0]["embeds"][0]["fields"]]


def test_the_database_size_alerts_and_recovers_on_its_own_row(
    monkeypatch: pytest.MonkeyPatch, sent: list[dict[str, Any]]
) -> None:
    monkeypatch.setenv("DEV_ALERTS_MENTION_USER_ID", FAKE_ID)
    sized(monkeypatch, 460)
    two_before, before = NOW - timedelta(days=2), NOW - timedelta(days=1)
    run(monkeypatch, daily(20, now=two_before), two_before)
    assert titles(sent) == [
        "Supabase database size: near the 500 MB cap",
        "Daily infrastructure digest · 26 Sep",
    ]
    alert, digest = sent
    assert "flags" not in alert
    assert alert["content"] == f"<@{FAKE_ID}> the database needs action today"
    assert alert["embeds"][0]["color"] == egress_monitor.RED
    assert alert["embeds"][0]["description"] == (
        "The database is at ~460 MB, 92% of the 500 MB cap."
    )
    assert digest["embeds"][0]["color"] == egress_monitor.RED
    assert digest["embeds"][0]["description"] == "The database is near its size cap."
    db, egress = state(egress_monitor.DB_KEY), state()
    assert db is not None and db.level == "red"
    assert egress is not None and egress.level == "normal"
    sent.clear()

    run(monkeypatch, daily(20, now=before), before)
    assert titles(sent) == ["Daily infrastructure digest · 27 Sep"]
    sent.clear()

    # Egress turns red on the day the database recovers: each check posts its own change
    sized(monkeypatch, 300)
    run(monkeypatch, daily(200))
    assert titles(sent) == [
        "Supabase egress: on track to pass the 5 GB cap",
        "Supabase database size: back under 90% of the cap",
        "Daily infrastructure digest · 28 Sep",
    ]
    recovery = sent[1]
    assert recovery["flags"] == egress_monitor.SILENT
    assert recovery["embeds"][0]["fields"][1]["value"].startswith("2 days, since <t:")
    db, egress = state(egress_monitor.DB_KEY), state()
    assert db is not None and db.level == "normal"
    assert egress is not None and egress.level == "red"


def test_an_undelivered_database_alert_posts_again_on_the_next_run(
    monkeypatch: pytest.MonkeyPatch, sent: list[dict[str, Any]]
) -> None:
    sized(monkeypatch, 480)
    monkeypatch.delenv("DEV_ALERTS_WEBHOOK_URL")
    run(monkeypatch, daily(20))
    assert state(egress_monitor.DB_KEY) is None
    current = state()
    assert current is not None and current.level == "normal"

    monkeypatch.setenv("DEV_ALERTS_WEBHOOK_URL", "https://discord.test/webhook")
    run(monkeypatch, daily(20))
    assert titles(sent)[0] == "Supabase database size: near the 500 MB cap"
    db = state(egress_monitor.DB_KEY)
    assert db is not None and db.level == "red"


def test_an_unavailable_snapshot_still_checks_the_database_size(
    monkeypatch: pytest.MonkeyPatch, sent: list[dict[str, Any]]
) -> None:
    sized(monkeypatch, 470)
    egress_monitor.report(egress_snapshot.unavailable("down"), NOW)
    assert titles(sent) == [
        "Egress snapshot could not run",
        "Supabase database size: near the 500 MB cap",
    ]


def test_a_failed_size_read_shows_in_the_digest_and_the_run_goes_on(
    monkeypatch: pytest.MonkeyPatch,
    sent: list[dict[str, Any]],
    caplog: pytest.LogCaptureFixture,
) -> None:
    def broken() -> None:
        raise RuntimeError("connection to host secret-host failed")

    monkeypatch.setattr(egress_monitor, "database_mb", broken)
    run(monkeypatch, daily(20))
    fields = {f["name"]: f["value"] for f in sent[0]["embeds"][0]["fields"]}
    assert fields["Database size"] == "not read (RuntimeError)"
    assert state(egress_monitor.DB_KEY) is None
    current = state()
    assert current is not None and current.level == "normal"
    assert "RuntimeError" in caplog.text and "secret-host" not in caplog.text


class DeniedError(Exception):
    sqlstate = "42501"


def fake_sessions(
    monkeypatch: pytest.MonkeyPatch, first: Exception, total: int
) -> list[str]:
    """A Postgres session whose first query raises `first` and whose next answers `total`."""
    queries: list[str] = []

    class Fake:
        def __enter__(self) -> Self:
            return self

        def __exit__(self, *args: object) -> None: ...

        def get_bind(self) -> SimpleNamespace:
            return SimpleNamespace(dialect=SimpleNamespace(name="postgresql"))

        def execute(self, query: object) -> SimpleNamespace:
            queries.append(str(query))
            if len(queries) == 1:
                raise first
            return SimpleNamespace(scalar_one=lambda: total)

    monkeypatch.setattr(egress_monitor, "Session", Fake)
    return queries


def test_without_the_right_to_read_every_database_the_size_is_this_one(
    monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    denied = DBAPIError("SELECT", {}, DeniedError("permission denied"))
    queries = fake_sessions(monkeypatch, denied, 300 * 1024 * 1024)
    assert egress_monitor.database_mb() == 300
    assert queries[1] == "SELECT pg_database_size(current_database())"
    assert "DBAPIError" in caplog.text and "permission denied" not in caplog.text


def test_any_other_failed_size_read_raises_to_the_run(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_sessions(monkeypatch, DBAPIError("SELECT", {}, Exception("gone")), 1)
    with pytest.raises(DBAPIError):
        egress_monitor.database_mb()


def test_a_baseline_digest_is_red_when_the_database_is(
    sent: list[dict[str, Any]], monkeypatch: pytest.MonkeyPatch
) -> None:
    sized(monkeypatch, 480)
    run(monkeypatch, [])
    digest = sent[-1]["embeds"][0]
    assert digest["color"] == egress_monitor.RED
    assert digest["description"] == (
        "The database is near its size cap. "
        "Baseline taken. First figures after the next run."
    )


def test_the_route_list_gives_way_before_the_dashboards() -> None:
    links = {"Supabase usage": "https://supabase.test/usage"}
    # Over by 164 with a long list: cut. Over by more than a 100-character list: dropped
    for routes, last, kept in [(1024, 1000, "cut"), (100, 870, "dropped")]:
        many = [
            *[egress_monitor.field(f"f{i}", "x" * 1000) for i in range(4)],
            egress_monitor.field("Busiest routes (rows)", "r" * routes, inline=False),
            egress_monitor.field("f4", "x" * 1000),
            egress_monitor.field("f5", "x" * last),
        ]
        if kept == "cut":
            many.pop()
        payload = egress_monitor.message(NOW, 0, "t", "d", many, links=links)
        embed = payload["embeds"][0]
        found = {f["name"]: f["value"] for f in embed["fields"]}
        assert size(payload) <= 6000
        assert embed["fields"][-1]["name"] == "Dashboards"
        assert "f4" in found
        if kept == "cut":
            assert found["Busiest routes (rows)"].endswith("r…")
            assert len(found["Busiest routes (rows)"]) < routes
        else:
            assert "Busiest routes (rows)" not in found and "f5" in found


TOKEN = "vercel-test-token"


def day(**counts: object) -> dict[str, Any]:
    """One day of the usage answer: zero for each meter not given, plus a field we ignore."""
    return {"date": "2026-09-28", "other_count": 7, **counts}


@pytest.fixture
def vercel(
    monkeypatch: pytest.MonkeyPatch, sent: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """The GETs sent to the Vercel API; each test sets the answer with `answer`."""
    monkeypatch.setenv("VERCEL_USAGE_TOKEN", TOKEN)
    monkeypatch.setenv("VERCEL_TEAM_ID", "team_test")
    return []


def answer(
    monkeypatch: pytest.MonkeyPatch,
    calls: list[dict[str, Any]],
    status: int = 200,
    days: list[dict[str, Any]] | None = None,
) -> None:
    class Response:
        status_code = status

        def raise_for_status(self) -> None:
            if status >= 400:
                error = egress_monitor.requests.HTTPError(f"{status} for url")
                error.response = self  # type: ignore[assignment]
                raise error

        def json(self) -> dict[str, Any]:
            return {"data": days or []}

    def get(url: str, **kwargs: object) -> Response:
        calls.append({"url": url, **kwargs})
        return Response()

    monkeypatch.setattr(egress_monitor.requests, "get", get)


# 214,531 invocations, 49.9 GB-hours, 364,870 requests half from the cache, 2.35 GB in and out
USAGE = [
    day(
        function_invocation_successful_count=200_000,
        function_invocation_error_count=14_000,
        function_execution_successful_gb_hours=40.0,
        function_execution_error_gb_hours=9.0,
        request_hit_count=182_435,
        request_miss_count=100_000,
        bandwidth_incoming_bytes=50_000_000,
        bandwidth_outgoing_bytes=1_950_000_000,
    ),
    day(
        function_invocation_timeout_count=500,
        function_invocation_throttle_count=31,
        function_execution_timeout_gb_hours=0.9,
        request_miss_count=82_435,
        bandwidth_outgoing_bytes=350_000_000,
    ),
]


def vercel_field(payload: dict[str, Any]) -> str | None:
    fields = {f["name"]: f for f in payload["embeds"][0]["fields"]}
    found = fields.get("Vercel, last 30 days")
    if found is None:
        return None
    assert found["inline"] is False
    return found["value"]


def test_the_digest_sums_the_vercel_meters_over_a_rolling_30_days(
    monkeypatch: pytest.MonkeyPatch,
    sent: list[dict[str, Any]],
    vercel: list[dict[str, Any]],
) -> None:
    answer(monkeypatch, vercel, days=USAGE)
    run(monkeypatch, daily(20))
    assert titles(sent) == ["Daily infrastructure digest · 28 Sep"]
    assert vercel_field(sent[0]) == (
        "Invocations 214,531 · 21% of the Hobby limit\n"
        "Function GB-hours 49.9 · 14% of the Hobby limit\n"
        "Requests 364,870 · 36% of the Hobby limit\n"
        "Bandwidth 2.35 GB · 2% of the Hobby limit\n"
        "Cache hits 50%"
    )
    (call,) = vercel
    assert call["url"] == "https://api.vercel.com/v2/usage"
    assert call["headers"] == {"Authorization": f"Bearer {TOKEN}"}
    assert call["timeout"] == 10
    # A minute before the run, back 30 days: never in the future, never over 31 days
    assert call["params"] == {
        "teamId": "team_test",
        "type": "requests",
        "from": "2026-08-30T00:29:00.000Z",
        "to": "2026-09-29T00:29:00.000Z",
    }
    current = state(egress_monitor.VERCEL_KEY)
    assert current is not None and current.level == "normal"


@pytest.mark.parametrize("unset", ["VERCEL_USAGE_TOKEN", "VERCEL_TEAM_ID"])
def test_without_both_variables_vercel_is_skipped(
    monkeypatch: pytest.MonkeyPatch,
    sent: list[dict[str, Any]],
    vercel: list[dict[str, Any]],
    unset: str,
) -> None:
    answer(monkeypatch, vercel, days=USAGE)
    monkeypatch.setenv(unset, " ")
    run(monkeypatch, daily(20))
    assert vercel == []
    assert vercel_field(sent[0]) is None
    assert state(egress_monitor.VERCEL_KEY) is None


def test_a_meter_at_80_percent_alerts_once_and_recovers_under_it(
    monkeypatch: pytest.MonkeyPatch,
    sent: list[dict[str, Any]],
    vercel: list[dict[str, Any]],
) -> None:
    monkeypatch.setenv("DEV_ALERTS_MENTION_USER_ID", FAKE_ID)
    high = [day(request_miss_count=800_000, function_execution_successful_gb_hours=300)]
    answer(monkeypatch, vercel, days=high)
    before = NOW - timedelta(days=1)
    run(monkeypatch, daily(20, now=before), before)
    assert titles(sent) == [
        "Vercel usage: near the included limit",
        "Daily infrastructure digest · 27 Sep",
    ]
    alert, digest = sent
    assert alert["content"] == f"<@{FAKE_ID}> Vercel usage needs action today"
    assert alert["embeds"][0]["description"] == (
        "Function GB-hours at 83% and Requests at 80% of the included usage "
        "over the last 30 days. "
        "Hobby pauses the feature for 30 days when a limit is hit."
    )
    assert digest["embeds"][0]["color"] == egress_monitor.RED
    assert digest["embeds"][0]["description"] == (
        "Vercel usage is near the included limit."
    )
    sent.clear()

    run(monkeypatch, daily(20))
    assert titles(sent) == ["Daily infrastructure digest · 28 Sep"]
    sent.clear()

    answer(monkeypatch, vercel, days=[day(request_miss_count=799_999)])
    after = NOW + timedelta(days=1)
    run(monkeypatch, daily(20, now=after), after)
    assert titles(sent) == [
        "Vercel usage: back under 80%",
        "Daily infrastructure digest · 29 Sep",
    ]
    assert sent[0]["flags"] == egress_monitor.SILENT
    assert sent[0]["embeds"][0]["fields"][1]["value"].startswith("2 days, since <t:")
    current = state(egress_monitor.VERCEL_KEY)
    assert current is not None and current.level == "normal"


@pytest.mark.parametrize("status", [401, 403])
def test_a_rejected_token_alerts_once_and_a_good_read_says_so(
    monkeypatch: pytest.MonkeyPatch,
    sent: list[dict[str, Any]],
    vercel: list[dict[str, Any]],
    caplog: pytest.LogCaptureFixture,
    status: int,
) -> None:
    answer(monkeypatch, vercel, status=status)
    before = NOW - timedelta(days=1)
    run(monkeypatch, daily(20, now=before), before)
    run(monkeypatch, daily(20))
    assert titles(sent) == [
        "Vercel usage could not be read: token rejected",
        "Daily infrastructure digest · 27 Sep",
        "Daily infrastructure digest · 28 Sep",
    ]
    assert vercel_field(sent[1]) is None
    current = state(egress_monitor.VERCEL_KEY)
    assert current is not None and current.level == "unavailable"
    assert all(TOKEN not in r.getMessage() for r in caplog.records)
    sent.clear()

    answer(monkeypatch, vercel, days=USAGE)
    after = NOW + timedelta(days=1)
    run(monkeypatch, daily(20, now=after), after)
    assert titles(sent) == [
        "Vercel usage: read again",
        "Daily infrastructure digest · 29 Sep",
    ]


def test_an_undelivered_vercel_alert_posts_again_on_the_next_run(
    monkeypatch: pytest.MonkeyPatch,
    sent: list[dict[str, Any]],
    vercel: list[dict[str, Any]],
) -> None:
    answer(monkeypatch, vercel, status=401)
    monkeypatch.delenv("DEV_ALERTS_WEBHOOK_URL")
    run(monkeypatch, daily(20))
    assert state(egress_monitor.VERCEL_KEY) is None
    monkeypatch.setenv("DEV_ALERTS_WEBHOOK_URL", "https://discord.test/webhook")
    run(monkeypatch, daily(20))
    assert titles(sent)[0] == "Vercel usage could not be read: token rejected"


@pytest.mark.parametrize("status", [500, 503])
def test_a_server_error_shows_not_read_and_keeps_the_level(
    monkeypatch: pytest.MonkeyPatch,
    sent: list[dict[str, Any]],
    vercel: list[dict[str, Any]],
    caplog: pytest.LogCaptureFixture,
    status: int,
) -> None:
    answer(monkeypatch, vercel, days=USAGE)
    before = NOW - timedelta(days=1)
    run(monkeypatch, daily(20, now=before), before)
    sent.clear()

    answer(monkeypatch, vercel, status=status)
    run(monkeypatch, daily(20))
    assert titles(sent) == ["Daily infrastructure digest · 28 Sep"]
    assert vercel_field(sent[0]) == f"not read (HTTPError {status})"
    assert f"HTTPError {status}" in caplog.text
    assert all(TOKEN not in r.getMessage() for r in caplog.records)
    current = state(egress_monitor.VERCEL_KEY)
    assert current is not None and current.updated_at == before


def test_a_timeout_shows_not_read_and_logs_no_token(
    monkeypatch: pytest.MonkeyPatch,
    sent: list[dict[str, Any]],
    vercel: list[dict[str, Any]],
    caplog: pytest.LogCaptureFixture,
) -> None:
    def slow(url: str, **kwargs: object) -> None:
        raise egress_monitor.requests.Timeout(f"{url} {kwargs['headers']}")

    monkeypatch.setattr(egress_monitor.requests, "get", slow)
    run(monkeypatch, daily(20))
    assert titles(sent) == ["Daily infrastructure digest · 28 Sep"]
    assert vercel_field(sent[0]) == "not read (Timeout)"
    assert "Timeout" in caplog.text
    assert all(TOKEN not in r.getMessage() for r in caplog.records)
    assert state(egress_monitor.VERCEL_KEY) is None


@pytest.mark.parametrize(
    ("days", "error"),
    [
        ([day(request_hit_count="many")], "TypeError"),
        ([day(bandwidth_outgoing_bytes=float("inf"))], "OverflowError"),
        ([None], "AttributeError"),
    ],
)
def test_a_bad_body_shows_not_read(
    monkeypatch: pytest.MonkeyPatch,
    sent: list[dict[str, Any]],
    vercel: list[dict[str, Any]],
    days: list[Any],
    error: str,
) -> None:
    answer(monkeypatch, vercel, days=days)
    run(monkeypatch, daily(20))
    assert vercel_field(sent[0]) == f"not read ({error})"
    assert state(egress_monitor.VERCEL_KEY) is None


def test_the_token_alert_links_the_vercel_dashboard(
    monkeypatch: pytest.MonkeyPatch,
    sent: list[dict[str, Any]],
    vercel: list[dict[str, Any]],
) -> None:
    monkeypatch.setenv("DEV_ALERTS_VERCEL_USAGE_URL", "https://vercel.test/usage")
    monkeypatch.setenv("DEV_ALERTS_SUPABASE_USAGE_URL", "https://supabase.test/usage")
    answer(monkeypatch, vercel, status=401)
    run(monkeypatch, daily(20))
    embed = sent[0]["embeds"][0]
    assert embed["title"] == "Vercel usage could not be read: token rejected"
    assert embed["fields"][-1]["value"] == "[Vercel usage](https://vercel.test/usage)"
    assert "url" not in embed
    assert embed["footer"]["text"] == egress_monitor.MONITOR_FOOTER


def test_a_digest_with_every_field_fits_discords_limits(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    usage = egress_monitor.Vercel(10**12, 10.0**9, 10**12, 10**11, 10**18)
    m = egress_monitor.meters(daily(20_000), NOW)
    payload = egress_monitor.digest(m, [], None, 499.0, None, usage)
    names = [f["name"] for f in payload["embeds"][0]["fields"]]
    assert names[3:5] == ["Database size", "Vercel, last 30 days"]
    assert size(payload) <= 6000


def test_the_unavailable_alert_starts_its_reason_with_a_capital() -> None:
    payload = egress_monitor.unavailable_alert(
        "the pg_stat_statements extension is not installed",
        datetime(2026, 9, 27, tzinfo=UTC),
        None,
    )
    assert payload["embeds"][0]["description"].startswith(
        "The pg_stat_statements extension"
    )
