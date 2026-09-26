---
type: Data Model
title: egress_snapshot
description: "One daily copy of pg_stat_statements: the cumulative calls and rows of each statement, role and nesting level at the time of the copy, kept 35 days."
resource: ../../../../app/models/egress_snapshot.py
tags: [deploy, data]
generated: { by: claude-code/claude-opus-5-5, at: 2026-09-26T10:00:00Z }
sources:
  - id: model
    resource: ../../../../app/models/egress_snapshot.py
    title: EgressSnapshot
  - id: service
    resource: ../../../../app/services/egress_snapshot.py
    title: take, summary and recent
---

# Schema

| Column | Type | Null | Meaning |
|---|---|---|---|
| `taken_at` | TIMESTAMPTZ | no | When the job copied the statistics, in UTC; one value per run. |
| `queryid` | BIGINT | no | The statement's `queryid` in pg_stat_statements. |
| `dbid` | BIGINT | no | The oid of the database the statement ran in. |
| `userid` | BIGINT | no | The oid of the role that ran the statement. |
| `toplevel` | BOOLEAN | no | False for a statement run inside a function. |
| `calls` | BIGINT | no | Calls since the counter was last reset. |
| `rows` | BIGINT | no | Rows returned or changed since the counter was last reset. |

# Keys and joins

Primary key (`taken_at`, `queryid`, `dbid`, `userid`, `toplevel`), the key of a pg_stat_statements row. The statement text is in [egress_statement](egress_statement.md) under the same (`queryid`, `dbid`). No foreign keys.

# Rules

`GET /jobs/egress-snapshot` writes one row per statement in one `INSERT ... SELECT` on the server, then deletes the rows older than 35 days. A run within an hour of the last snapshot writes nothing. Statements that name `egress_snapshot`, `egress_statement`, `egress_ledger` or `pg_stat_statements` are not copied, so the job, the ledger's per-request write and any statistics read do not count toward the estimate.

A window is two consecutive runs. A row's rows in a window are its current count minus the count before under the same key, so one role's reset never re-counts another role's rows; a count that went down was reset and counts in full, and a statement new since the run before counts in full. The estimate is the window's rows times 100 bytes, the rate `app/core/egress_stats.py` states. See [scheduled jobs](../../api/jobs.md).
