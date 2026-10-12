---
type: Data Model
title: cup_veto_step
description: One taken step of a cup series' map veto, with the side, the action, the map and who entered it.
resource: ../../../../app/models/cup_series.py
tags: [events, series, maps, data]
generated: { by: claude-code/claude-opus-5-5, at: 2026-10-12T21:00:00Z }
sources:
  - id: model
    resource: ../../../../app/models/cup_series.py
    title: CupVetoStep
  - id: veto
    resource: ../../../../app/services/cup_veto.py
    title: board and take
---

# Schema

| Column | Type | Null | Meaning |
|---|---|---|---|
| `series_id` | INTEGER | no | The cup series. Part of the key. |
| `step_no` | INTEGER | no | The step number, from 1, in the order the series vetoes by. Part of the key. |
| `side` | VARCHAR(1) | no | `A` (side 1) or `B` (side 2). |
| `action` | VARCHAR(4) | no | `ban` or `pick`. |
| `map_id` | INTEGER | no | The map the step took. A map used by any step leaves the board. |
| `entered_by` | INTEGER | yes | The player who typed the step in. Null when the step took itself or a runner has no player row. |

# Keys and joins

Primary key (`series_id`, `step_no`). Foreign keys: `series_id` to [cup_series](cup_series.md), cascade; `map_id` to [maps](maps.md); `entered_by` to [users](users.md), set null.

# Rules

- The order is the series' own by its best-of when the cup vetoes that way, else the cup's `pick_ban` list. Only the steps taken are stored.
- A player of a side takes that side's steps and takes back what they entered; a runner of the cup records any step and takes back the last one. `GET` and `PUT /cup-series/{id}/veto` serve the board.
- Swapping a player into an open series, or changing the cup's pool, is refused or starts the veto over: see [events module](../../concepts/events-module.md#cup-series).
