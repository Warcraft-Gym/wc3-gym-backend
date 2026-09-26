---
type: Data Model
title: monitor_state
description: "The last level of each monitor check, one row per check: the level, when the check reached it and when a run last wrote the row."
resource: ../../../../app/models/monitor_state.py
tags: [deploy, data]
generated: { by: claude-code/claude-opus-5-5, at: 2026-09-26T16:00:00Z }
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
| `key` | TEXT | no | The check, `egress` for the egress snapshot. |
| `level` | TEXT | no | `normal`, `amber`, `red` or `unavailable`. |
| `since` | TIMESTAMPTZ | no | When the level began, in UTC: the start of the window that set it, or the run time for `unavailable`. |
| `updated_at` | TIMESTAMPTZ | no | When a run last wrote the row, in UTC. |

# Keys and joins

Primary key (`key`). No foreign keys.

# Rules

Every egress snapshot run that writes a snapshot, and every run that fails, sets the `egress` row to the level it measured; a run within an hour of the last snapshot leaves it alone. `since` moves only when the level changes. A change to `red` or `unavailable` is stored only once its alert is posted, so an alert that did not reach Discord posts again on the next run. The row is what makes an alert post once per change of level rather than once per run. See [scheduled jobs](../../api/jobs.md#the-egress-monitor).
