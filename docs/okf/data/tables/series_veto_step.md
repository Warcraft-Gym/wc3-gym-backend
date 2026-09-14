---
type: Data Model
title: series_veto_step
description: One taken step of a series' map veto, with the side, the action, the map and who entered it; the order itself comes from the event's pick_ban.
resource: ../../../../app/models/series_veto_step.py
tags: [schema, events]
generated: { by: claude-code/claude-fable-5-1, at: 2026-09-14T15:15:00Z }
sources:
  - id: model
    resource: ../../../../app/models/series_veto_step.py
    title: DBSeriesVetoStep
  - id: veto
    resource: ../../../../app/services/series_veto.py
    title: step, record and undo
---

# Schema

| Column | Type | Null | Meaning |
|---|---|---|---|
| `series_id` | INTEGER | no | The series. Part of the key. |
| `step_no` | INTEGER | no | The step number, from 1, in the order of the event's `pick_ban`. Part of the key. |
| `side` | VARCHAR | no | `A` (player1) or `B` (player2). |
| `action` | VARCHAR | no | `ban` or `pick`. |
| `map_id` | INTEGER | no | The map the step took. A map used by any step leaves the board. |
| `entered_by` | INTEGER | yes | The player who typed the step in. Null when the step took itself or the admin has no player row. |

# Keys and joins

Primary key (`series_id`, `step_no`). Foreign keys: `series_id` to [series](series.md), cascade; `map_id` to [maps](maps.md); `entered_by` to [users](users.md), set null.

# Rules

The board is derived from `pick_ban`, the map pool and `map_rules`; only the steps taken are stored. An undo deletes the last row. The picks ride on the series payload as `player1_pick_map` and `player2_pick_map`. See [series reporting](../../concepts/series-reporting.md).
