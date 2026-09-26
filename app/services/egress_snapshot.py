"""The daily egress snapshot: pg_stat_statements copied into the database and diffed in SQL.

The copy is an INSERT ... SELECT on the server, so a run returns only its summary to the client.
"""

import logging
import os
from datetime import datetime, timedelta

import requests
from sqlalchemy import BigInteger, Integer, Text, bindparam, text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.orm import Session as OrmSession

from app.core.db import Session
from app.core.egress_stats import BYTES_PER_ROW
from app.models.egress_snapshot import (
    EgressSnapshotResult,
    EgressStatementRows,
    EgressWindow,
)
from app.models.types import UTCDateTime, utcnow

log = logging.getLogger(__name__)

# The per-project budget of `just db check`: 80 MB a day fits 5 GB a month
BUDGET_MB_PER_DAY = 80.0
KEEP = timedelta(days=35)
TOP = 10

# The job's own statements, the ledger's per-request upsert and any statistics scan are not client egress
OWN = r"query !~ 'egress_snapshot|egress_statement|egress_ledger|pg_stat_statements'"
# A run this soon after the last would extrapolate a short window into a false day rate
MIN_GAP = timedelta(hours=1)

SAVE_STATEMENTS = text(
    "INSERT INTO egress_statement (queryid, dbid, query) "
    "SELECT queryid, dbid::bigint, left(regexp_replace(min(query), '\\s+', ' ', 'g'), 150) "
    f"FROM pg_stat_statements WHERE queryid IS NOT NULL AND {OWN} "
    "GROUP BY queryid, dbid ON CONFLICT DO NOTHING"
)
SAVE_SNAPSHOT = text(
    "INSERT INTO egress_snapshot (taken_at, queryid, dbid, userid, toplevel, calls, rows) "
    "SELECT :taken, queryid, dbid::bigint, userid::bigint, toplevel, calls, rows "
    f"FROM pg_stat_statements WHERE queryid IS NOT NULL AND {OWN}"
).bindparams(bindparam("taken", type_=UTCDateTime()))
PRUNE_SNAPSHOTS = text(
    "DELETE FROM egress_snapshot WHERE taken_at < :cutoff"
).bindparams(bindparam("cutoff", type_=UTCDateTime()))
PRUNE_STATEMENTS = text(
    "DELETE FROM egress_statement WHERE NOT EXISTS (SELECT 1 FROM egress_snapshot e "
    "WHERE e.queryid = egress_statement.queryid AND e.dbid = egress_statement.dbid)"
)

# Each counter's calls and rows since the snapshot before, one counter per statement, role and
# nesting level; a counter that went down was reset, and one new since then counts in full.
DELTA = """
WITH times AS (
    SELECT taken_at, lag(taken_at) OVER (ORDER BY taken_at) AS prev_at
    FROM (SELECT DISTINCT taken_at FROM egress_snapshot) AS t
), delta AS (
    SELECT t.taken_at, t.prev_at, c.queryid, c.dbid,
        CASE WHEN p.calls IS NULL OR c.calls < p.calls THEN c.calls ELSE c.calls - p.calls END AS calls,
        CASE WHEN p.rows IS NULL OR c.rows < p.rows THEN c.rows ELSE c.rows - p.rows END AS rows
    FROM times t
    JOIN egress_snapshot c ON c.taken_at = t.taken_at
    LEFT JOIN egress_snapshot p
        ON p.taken_at = t.prev_at AND p.queryid = c.queryid AND p.dbid = c.dbid
        AND p.userid = c.userid AND p.toplevel = c.toplevel
    WHERE t.prev_at IS NOT NULL AND t.taken_at >= :since
)
"""
WINDOWS = (
    text(
        DELTA + "SELECT taken_at, prev_at, CAST(sum(calls) AS BIGINT) AS calls, "
        "CAST(sum(rows) AS BIGINT) AS rows "
        "FROM delta GROUP BY taken_at, prev_at ORDER BY taken_at"
    )
    .bindparams(bindparam("since", type_=UTCDateTime()))
    .columns(
        taken_at=UTCDateTime(), prev_at=UTCDateTime(), calls=BigInteger, rows=BigInteger
    )
)
TOP_STATEMENTS = (
    text(
        DELTA + "SELECT coalesce(min(s.query), '') AS query, "
        "CAST(sum(d.calls) AS BIGINT) AS calls, CAST(sum(d.rows) AS BIGINT) AS rows "
        "FROM delta d LEFT JOIN egress_statement s ON s.queryid = d.queryid AND s.dbid = d.dbid "
        "WHERE d.taken_at = :since GROUP BY d.queryid, d.dbid HAVING sum(d.rows) > 0 "
        "ORDER BY rows DESC LIMIT :top"
    )
    .bindparams(
        bindparam("since", type_=UTCDateTime()), bindparam("top", type_=Integer)
    )
    .columns(query=Text, calls=BigInteger, rows=BigInteger)
)
LAST = text("SELECT max(taken_at) AS taken_at FROM egress_snapshot").columns(
    taken_at=UTCDateTime()
)
COUNT = text("SELECT count(*) FROM egress_snapshot WHERE taken_at = :taken").bindparams(
    bindparam("taken", type_=UTCDateTime())
)


def window(start: datetime, end: datetime, calls: int, rows: int) -> EgressWindow:
    hours = (end - start).total_seconds() / 3600
    mb = rows * BYTES_PER_ROW / 1e6
    per_day = mb / max(hours, 0.01) * 24
    return EgressWindow(
        start=start,
        end=end,
        hours=round(hours, 2),
        calls=calls,
        rows=rows,
        estimated_mb=round(mb, 1),
        mb_per_day=round(per_day, 1),
        over_budget=per_day > BUDGET_MB_PER_DAY,
    )


def windows(session: OrmSession, since: datetime) -> list[EgressWindow]:
    """One window per snapshot taken at or after `since`, oldest first."""
    return [
        window(r.prev_at, r.taken_at, r.calls or 0, r.rows or 0)
        for r in session.execute(WINDOWS, {"since": since})
    ]


def summary(session: OrmSession, taken: datetime) -> EgressSnapshotResult:
    """The snapshot taken at `taken` against the one before it."""
    found = [w for w in windows(session, taken) if w.end == taken]
    top = session.execute(TOP_STATEMENTS, {"since": taken, "top": TOP}).all()
    return EgressSnapshotResult(
        available=True,
        taken_at=taken,
        statements=session.execute(COUNT, {"taken": taken}).scalar_one(),
        budget_mb_per_day=BUDGET_MB_PER_DAY,
        window=found[0] if found else None,
        top=[EgressStatementRows(query=q, calls=c, rows=n) for q, c, n in top],
    )


def unavailable(reason: str) -> EgressSnapshotResult:
    return EgressSnapshotResult(
        available=False, reason=reason, budget_mb_per_day=BUDGET_MB_PER_DAY
    )


def take() -> EgressSnapshotResult:
    """Copy pg_stat_statements, drop what is older than 35 days, and diff with the last copy;
    within an hour of the last copy, write nothing."""
    taken = utcnow()
    with Session() as session:
        last = session.scalar(LAST)
        if last is not None and taken - last < MIN_GAP:
            minutes = int((taken - last).total_seconds() // 60)
            return EgressSnapshotResult(
                available=True,
                skipped=f"last snapshot {minutes} min ago",
                taken_at=last,
                budget_mb_per_day=BUDGET_MB_PER_DAY,
            )
        if session.get_bind().dialect.name != "postgresql":
            return unavailable("pg_stat_statements needs Postgres")
        if session.scalar(text("SELECT to_regclass('pg_stat_statements')")) is None:
            return unavailable("the pg_stat_statements extension is not installed")
        try:
            session.execute(SAVE_STATEMENTS)
            session.execute(SAVE_SNAPSHOT, {"taken": taken})
        except DBAPIError as error:
            session.rollback()
            return unavailable(str(error.orig).splitlines()[0])
        session.execute(PRUNE_SNAPSHOTS, {"cutoff": taken - KEEP})
        session.execute(PRUNE_STATEMENTS)
        result = summary(session, taken)
        session.commit()
    return result


def recent(days: int) -> list[EgressWindow]:
    """The windows of the snapshots taken in the last `days` days, oldest first."""
    with Session() as session:
        return windows(session, utcnow() - timedelta(days=days))


def alert_text(result: EgressSnapshotResult) -> str | None:
    """The #webhooks message for a run that failed or went over budget; None when all is well."""
    if not result.available:
        return f"Egress snapshot could not run: {result.reason}"
    w = result.window
    if w is None or not w.over_budget:
        return None
    lines = [
        (
            f"Supabase egress over budget: ~{w.mb_per_day:,.0f} MB/day "
            f"(budget {result.budget_mb_per_day:.0f}), {w.rows:,} rows "
            f"from {w.start:%d %b %H:%M} to {w.end:%d %b %H:%M} UTC"
        )
    ]
    lines += [
        f"- {s.rows:,} rows, {s.calls:,} calls: `{s.query[:90]}`"
        for s in result.top[:3]
    ]
    return "\n".join(lines)


def alert(result: EgressSnapshotResult) -> None:
    """Post alert_text to the DEV_ALERTS_WEBHOOK_URL channel webhook; never fails the job."""
    url = os.getenv("DEV_ALERTS_WEBHOOK_URL")
    message = alert_text(result)
    if not url or message is None:
        return
    try:
        requests.post(
            url,
            json={"content": message, "allowed_mentions": {"parse": []}},
            timeout=10,
        ).raise_for_status()
    except requests.RequestException as error:
        log.warning("egress alert not posted: %s", error)
