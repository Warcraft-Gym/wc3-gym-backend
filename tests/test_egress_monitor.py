"""The egress monitor: the cycle's level, the posts per change of level and the payload rules."""

import json
from datetime import UTC, date, datetime, timedelta
from json import loads
from typing import Any

import pytest
from httpx2 import Client

from app.core.db import Session
from app.models.egress_ledger import EgressLedger
from app.models.egress_snapshot import EgressWindow
from app.models.monitor_state import MonitorState
from app.services import egress_chart, egress_monitor, egress_snapshot
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

    def post(
        url: str,
        timeout: float,
        json: dict[str, Any] | None = None,
        data: dict[str, str] | None = None,
        files: dict[str, tuple[str, bytes, str]] | None = None,
    ) -> Sent:
        if json is not None:
            posts.append(json)
        else:
            # A multipart post: the payload as payload_json and the chart as files[0]
            assert data is not None and files is not None
            posts.append({**loads(data["payload_json"]), "_file": files["files[0]"]})
        return Sent()

    monkeypatch.setattr(egress_monitor.requests, "post", post)
    monkeypatch.setenv("DEV_ALERTS_WEBHOOK_URL", "https://discord.test/webhook")
    monkeypatch.delenv("DEV_ALERTS_MENTION_USER_ID", raising=False)
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


def state() -> MonitorState | None:
    with Session() as session:
        return session.get(MonitorState, egress_monitor.KEY)


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


def test_a_window_counts_toward_the_cycle_it_ends_in_but_every_recent_window_sets_the_rate() -> (
    None
):
    now = datetime(2026, 9, 27, 6, tzinfo=UTC)
    found = [w(datetime(2026, 9, 25, 23, tzinfo=UTC), 900), w(now, 60, hours=31)]
    m = egress_monitor.meters(found, now)
    assert m.cycle_mb == 60
    # 960 MB over 55 hours
    assert m.average_mb_per_day == pytest.approx(960 / 55 * 24)


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
    assert titles(sent) == ["Daily infrastructure digest · 28 Sep"]
    assert sent[0]["flags"] == egress_monitor.SILENT
    assert sent[0]["embeds"][0]["color"] == egress_monitor.BLUE
    sent.clear()

    run(monkeypatch, daily(200))
    assert titles(sent) == [
        "Supabase egress: on track to pass the 5 GB cap",
        "Daily infrastructure digest · 29 Sep",
    ]
    alert, digest = sent
    assert "flags" not in alert
    assert digest["flags"] == egress_monitor.SILENT
    assert digest["embeds"][0]["color"] == egress_monitor.RED
    current = state()
    assert current is not None and (current.level, current.since) == ("red", NOW)
    sent.clear()

    after = NOW + timedelta(days=1)
    run(monkeypatch, daily(200, now=after), after)
    assert titles(sent) == ["Daily infrastructure digest · 30 Sep"]
    current = state()
    assert current is not None and current.since == NOW


def test_red_to_normal_posts_a_silent_recovery_then_the_digest(
    monkeypatch: pytest.MonkeyPatch, sent: list[dict[str, Any]]
) -> None:
    before = NOW - timedelta(days=3)
    run(monkeypatch, daily(200, now=before), before)
    sent.clear()
    run(monkeypatch, daily(20))
    assert titles(sent) == [
        "Supabase egress: back under budget",
        "Daily infrastructure digest · 29 Sep",
    ]
    recovery = sent[0]
    assert recovery["flags"] == egress_monitor.SILENT
    assert recovery["embeds"][0]["color"] == egress_monitor.GREEN
    assert recovery["embeds"][0]["fields"][2]["name"] == "Red for"
    assert recovery["embeds"][0]["fields"][2]["value"].startswith("3 days, since <t:")


def test_amber_colours_the_digest_and_never_alerts(
    monkeypatch: pytest.MonkeyPatch, sent: list[dict[str, Any]]
) -> None:
    run(monkeypatch, daily(50, 2) + [w(NOW, 120)])
    assert titles(sent) == ["Daily infrastructure digest · 29 Sep"]
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
        "the pg_stat_statements extension is not installed."
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
    alert = egress_monitor.alert(m, long, NOW, FAKE_ID)
    assert alert["embeds"][0]["title"] == "Supabase egress: over the 5 GB cap"
    for payload in [
        alert,
        egress_monitor.digest(m, long),
        egress_monitor.recovery(m, "red", NOW - timedelta(days=2)),
        egress_monitor.unavailable_alert("x" * 5000, NOW, None),
    ]:
        embed = payload["embeds"][0]
        assert size(payload) <= 6000
        assert len(embed["title"]) <= 256 and len(embed["description"]) <= 4096
        assert len(embed["fields"]) <= 25
        assert all(len(f["value"]) <= 1024 for f in embed["fields"])
        assert embed["footer"]["text"] == egress_monitor.FOOTER
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


PNG = b"\x89PNG\r\n\x1a\n"


@pytest.mark.parametrize("n", [1, 2, 14, 20])
def test_the_chart_is_a_png_for_any_number_of_points(n: int) -> None:
    points = [(f"{d} Sep", [0.0, 52.0, 1128.0][d % 3]) for d in range(1, n + 1)]
    assert egress_chart.render(points, 80).startswith(PNG)


def test_the_digest_attaches_the_chart_from_two_windows(
    monkeypatch: pytest.MonkeyPatch, sent: list[dict[str, Any]]
) -> None:
    run(monkeypatch, [w(NOW, 50)])
    assert "image" not in sent[0]["embeds"][0] and "_file" not in sent[0]
    sent.clear()

    run(monkeypatch, daily(50, days=20))
    embed = sent[0]["embeds"][0]
    assert embed["image"] == {"url": "attachment://egress.png"}
    name, png, kind = sent[0]["_file"]
    assert (name, kind) == ("egress.png", "image/png") and png.startswith(PNG)


def test_a_chart_that_fails_to_draw_leaves_the_digest_without_it(
    monkeypatch: pytest.MonkeyPatch,
    sent: list[dict[str, Any]],
    caplog: pytest.LogCaptureFixture,
) -> None:
    def broken(points: object, budget: float) -> bytes:
        raise OSError("no font")

    monkeypatch.setattr(egress_chart, "render", broken)
    run(monkeypatch, daily(50))
    assert titles(sent) == ["Daily infrastructure digest · 29 Sep"]
    assert "image" not in sent[0]["embeds"][0] and "_file" not in sent[0]
    assert "OSError" in caplog.text


def test_alerts_and_recoveries_carry_no_chart(
    monkeypatch: pytest.MonkeyPatch, sent: list[dict[str, Any]]
) -> None:
    run(monkeypatch, daily(200))
    alert, digest = sent
    assert "image" not in alert["embeds"][0] and "_file" not in alert
    assert "_file" in digest
