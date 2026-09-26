---
type: Data Model
title: monitor_state
description: "The last level of each monitor check, one row per check: the level, when the check reached it and when a run last wrote the row."
resource: ../../../../app/models/monitor_state.py
tags: [deploy, data]
generated: { by: claude-code/claude-opus-5-5, at: 2026-09-26T22:00:00Z }
sources:
  - id: model
    resource: ../../../../app/models/monitor_state.py
    title: MonitorState
  - id: service
    resource: ../../../../app/services/egress_monitor.py
    title: report and crashed
---

# Schema

| Column | Type | Null | Meaning |
|---|---|---|---|
| `key` | TEXT | no | The check: `egress` for the egress snapshot, `db_size` for the database size, `vercel` for the Vercel usage. |
| `level` | TEXT | no | `normal`, `amber`, `red` or `unavailable`; `db_size` is `normal` or `red`; `vercel` is `normal`, `red` or `unavailable`. |
| `since` | TIMESTAMPTZ | no | When the level began, in UTC: the start of the window that set it, or the run time for `unavailable`. |
| `updated_at` | TIMESTAMPTZ | no | When a run last wrote the row, in UTC. |

# Keys and joins

Primary key (`key`). No foreign keys.

# Rules

Every egress snapshot run that writes a snapshot, and every run that fails, sets the `egress` row to the level it measured, the `db_size` row to the level of the database size when it was read, and the `vercel` row to the level of the Vercel usage when it was read or the token was rejected; a run within an hour of the last snapshot leaves them all alone. `since` moves only when the level changes. For each row, a change to `red` or `unavailable` is stored only once its alert is posted, so an alert that did not reach Discord posts again on the next run. The row is what makes an alert post once per change of level rather than once per run. See [scheduled jobs](../../api/jobs.md#the-egress-monitor).
