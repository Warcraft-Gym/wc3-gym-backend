"""Snapshot and report Supabase billed egress.

The bill is "Shared Pooler Egress": bytes Supavisor sends to clients. The pooler
publishes that counter, so we record it next to pg_stat_statements and diff two
snapshots to see which database and which statement grew.

usage: uv run python -m app.core.egress_stats snapshot [prod|staging|all]
       uv run python -m app.core.egress_stats report [prod|staging] [rows]
       uv run python -m app.core.egress_stats check [prod|staging] [budget_mb_per_day]

The credentials come from the environment (`just db` loads .env): VERCEL_PROD_DB_URL,
VERCEL_STAGING_DB_URL, SUPABASE_PROD_PROJECT_REF, SUPABASE_STAGING_PROJECT_REF,
SUPABASE_PROD_SECRET_KEY and SUPABASE_STAGING_SECRET_KEY.

Snapshots append one JSON line to data/egress/<env>.jsonl (gitignored).

One snapshot reads about 3,400 statement rows, which is roughly 0.4 MB of egress per
project. Twice a day costs about 1.6 MB a day, so do not poll this every minute.

ponytail: each line keeps the query text, so a snapshot is ~670 KB and the file grows
about 1.3 MB a day at two runs. Delete old lines, or key the text off queryid in a side
file, if the file ever matters.
"""

import base64
import json
import os
import re
import sys
import urllib.request
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import psycopg

OUT = Path(__file__).resolve().parents[2] / "data" / "egress"
# The pooler restarts reset its counters, so a negative delta means "restarted, skip".
POOLER_SEND = re.compile(
    r"^supavisor_client_network_send\{[^}]*} ([0-9.e+]+)$", re.MULTILINE
)
# Wire bytes per row returned, calibrated on 21-23 Sep 2026: 24.5 M rows against ~2.9 GB billed.
BYTES_PER_ROW = 100
NODE = ("node_network_transmit_bytes_total", "node_time_seconds")


def config(env: str) -> tuple[str, str, str]:
    """The project ref, secret key and database URL of one environment."""
    name = env.upper()
    return (
        os.environ[f"SUPABASE_{name}_PROJECT_REF"],
        os.environ[f"SUPABASE_{name}_SECRET_KEY"],
        os.environ[f"VERCEL_{name}_DB_URL"],
    )


def metrics(ref: str, key: str) -> dict[str, float]:
    token = base64.b64encode(f"service_role:{key}".encode()).decode()
    req = urllib.request.Request(
        f"https://{ref}.supabase.co/customer/v1/privileged/metrics",
        headers={"Authorization": f"Basic {token}"},
    )
    with urllib.request.urlopen(req, timeout=60) as resp:
        body = resp.read().decode()
    out = {"pooler_sent": sum(float(m.group(1)) for m in POOLER_SEND.finditer(body))}
    for name in NODE:
        m = re.search(rf"^{name}\{{[^}}]*}} ([0-9.e+]+)$", body, re.MULTILINE)
        if m:
            out[name.replace("node_network_", "").replace("_total", "")] = float(
                m.group(1)
            )
    return out


def statements(
    url: str,
) -> tuple[dict[str, dict[str, int]], dict[str, dict[str, Any]], int]:
    """Per-database totals and per-statement rows, across every database in the instance."""
    with psycopg.connect(
        url.replace("postgresql+psycopg://", "postgresql://"), connect_timeout=20
    ) as conn:
        cur = conn.cursor()
        cur.execute(
            "select coalesce(d.datname, s.dbid::text), sum(s.calls)::bigint, sum(s.rows)::bigint "
            "from pg_stat_statements s left join pg_database d on d.oid = s.dbid group by 1"
        )
        by_database = {
            name: {"calls": calls, "rows": rows} for name, calls, rows in cur.fetchall()
        }
        cur.execute(
            "select s.queryid, coalesce(d.datname, ''), s.calls, s.rows, "
            "left(regexp_replace(s.query, '\\s+', ' ', 'g'), 150) "
            "from pg_stat_statements s left join pg_database d on d.oid = s.dbid "
            "where s.queryid is not null"
        )
        rows = {
            f"{qid}": {"db": db, "calls": calls, "rows": n, "q": q}
            for qid, db, calls, n, q in cur.fetchall()
        }
        cur.execute("select sum(sessions)::bigint from pg_stat_database")
        found = cur.fetchone()
        sessions = (found[0] if found else 0) or 0
    return by_database, rows, sessions


def snapshot(envs: list[str], out: Path = OUT) -> None:
    out.mkdir(parents=True, exist_ok=True)
    for env in envs:
        ref, key, url = config(env)
        by_database, rows, sessions = statements(url)
        line = {
            "at": datetime.now(UTC).isoformat(timespec="seconds"),
            **metrics(ref, key),
            "sessions": sessions,
            "by_database": by_database,
            "statements": rows,
        }
        with (out / f"{env}.jsonl").open("a") as fh:
            fh.write(json.dumps(line) + "\n")
        print(
            f"{env}: pooler sent {line['pooler_sent'] / 1e6:.1f} MB so far, {len(rows)} statements"
        )


def report(env: str, limit: int = 15, out: Path = OUT) -> float:
    path = out / f"{env}.jsonl"
    if not path.exists():
        sys.exit(f"no snapshots yet: run `just db snapshot` at least twice ({path})")
    lines = [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
    if len(lines) < 2:
        sys.exit(f"only {len(lines)} snapshot(s); take another to compare")
    a, b = lines[-2], lines[-1]
    hours = (
        datetime.fromisoformat(b["at"]) - datetime.fromisoformat(a["at"])
    ).total_seconds() / 3600
    sent = b["pooler_sent"] - a["pooler_sent"]
    print(f"{env}: {a['at']} -> {b['at']}  ({hours:.1f} h)")
    # The bill follows rows returned, not the pooler counter: that counter resets on a
    # pooler restart and read 474 MB for the 21-23 Sep 2026 window the bill charged ~2.9 GB.
    rows_out = sum(
        now["rows"] - a["statements"].get(qid, {"rows": 0})["rows"]
        for qid, now in b["statements"].items()
    )
    est = rows_out * BYTES_PER_ROW
    rate = est / max(hours, 0.01) * 24 / 1e6
    print(
        f"  rows returned {rows_out:,}  ->  ~{est / 1e6:.0f} MB billed  ->  ~{rate:.0f} MB/day"
    )
    if sent >= 0:
        print(f"  pooler counter {sent / 1e6:.1f} MB (resets on restart; not the bill)")
    print(f"  new sessions {b['sessions'] - a['sessions']:,}")
    sent = est

    print("\n  by database (rows returned):")
    for name in sorted(set(a["by_database"]) | set(b["by_database"])):
        was = a["by_database"].get(name, {"calls": 0, "rows": 0})
        now = b["by_database"].get(name, {"calls": 0, "rows": 0})
        d_rows, d_calls = now["rows"] - was["rows"], now["calls"] - was["calls"]
        if d_rows or d_calls:
            print(f"    {name:<28} {d_rows:>12,} rows  {d_calls:>10,} calls")

    grew = []
    for qid, now in b["statements"].items():
        was = a["statements"].get(qid, {"calls": 0, "rows": 0})
        d_rows = now["rows"] - was["rows"]
        d_calls = now["calls"] - was["calls"]
        if d_rows > 0 or d_calls > 0:
            grew.append((d_rows, d_calls, now["db"], now["q"]))
    grew.sort(reverse=True)
    # Share of the window's billed bytes, split by rows returned. A rough split: a
    # statement returning few wide rows is under-charged, many narrow rows over-charged.
    total_rows = sum(row[0] for row in grew) or 1
    print(f"\n  top {limit} statements by rows returned:")
    for d_rows, d_calls, db, q in grew[:limit]:
        share = f"~{sent * d_rows / total_rows / 1e6:7.1f} MB" if sent > 0 else " " * 11
        print(f"   {share}  {d_rows:>10,} rows  {d_calls:>8,} calls  [{db}] {q[:90]}")
    return rate


def check(env: str, budget_mb_per_day: float) -> None:
    """Snapshot, then fail when the window's rate is over budget. For an unattended run."""
    snapshot([env])
    rate = report(env, 10)
    if rate > budget_mb_per_day:
        print(
            f"\nOVER BUDGET: {rate:.0f} MB/day against {budget_mb_per_day:.0f} MB/day"
        )
        sys.exit(2)
    print(f"\nwithin budget: {rate:.0f} MB/day against {budget_mb_per_day:.0f} MB/day")


if __name__ == "__main__":
    action = sys.argv[1] if len(sys.argv) > 1 else "snapshot"
    which = sys.argv[2] if len(sys.argv) > 2 else "all"
    if action == "snapshot":
        snapshot(["prod", "staging"] if which == "all" else [which])
    elif action == "report":
        report(
            which if which != "all" else "prod",
            int(sys.argv[3]) if len(sys.argv) > 3 else 15,
        )
    elif action == "check":
        check(
            which if which != "all" else "prod",
            float(sys.argv[3]) if len(sys.argv) > 3 else 80.0,
        )
    else:
        sys.exit(__doc__)
