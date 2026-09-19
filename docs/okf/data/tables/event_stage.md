---
type: Data Model
title: event_stage
description: One format played over the entrants of an event, with the points, the tie breaks and the advance rule; standings are computed from it, never stored.
resource: ../../../../app/models/event_stage.py
tags: [events, data]
generated: { by: claude-code/claude-fable-5-1, at: 2026-09-19T12:00:00Z }
verified: { by: process:test_okf, at: 2026-09-14T17:40:50Z }
sources:
  - id: model
    resource: ../../../../app/models/event_stage.py
    title: EventStage
  - id: events
    resource: ../../../../app/services/events.py
    title: EventService.set_stages and lock_seeds
  - id: engine
    resource: ../../../../app/services/stage_engine.py
    title: The engine reads every rule column
---

# Schema

| Column | Type | Null | Meaning |
|---|---|---|---|
| `id` | INTEGER | no | Primary key. |
| `event_id` | INTEGER | no | The event the stage belongs to. |
| `position` | INTEGER | no | The order stages play in; the first is 1. Unique per event. |
| `name` | VARCHAR | yes | A display name. |
| `format` | VARCHAR | no | `round_robin`, `gnl`, `single_elimination`, `double_elimination`, `swiss`, `koth` or `ffa`. A `gnl` stage refuses generate. |
| `best_of` | INTEGER | no | Games a series holds. A round may override it. |
| `series_per_entrant_per_round` | INTEGER | no | How many series each entrant plays per round of a round robin. At least 1. |
| `swiss_rounds` | INTEGER | yes | How many rounds a Swiss stage draws. Null means it draws on without end. |
| `points_by_place` | VARCHAR | yes | What each place of an FFA lobby pays, best first, as `4,3,2,1`. |
| `lobby_size` | INTEGER | yes | How many players an FFA lobby seats. |
| `map_rules` | VARCHAR | yes | One rule per game, comma-joined, as on the event. A generated series reads this column. |
| `scheduling_mode` | VARCHAR | no | Who sets the time of a series: `assigned` (an admin), `agreed` (the two sides) or `immediate` (nobody). |
| `ranking_rule` | VARCHAR | no | The tie breaks the table reads, in order, from `points`, `buchholz`, `game_diff`, `head_to_head`. Default `points,game_diff,head_to_head`. |
| `points_series_won` | INTEGER | no | Table points for a series won. |
| `points_series_drawn` | INTEGER | no | Table points for a series drawn. |
| `points_game_won` | INTEGER | no | Table points per game won. |
| `advance_count` | INTEGER | yes | How many of the standings carry into the next stage. Null means all of them. |
| `group_size` | INTEGER | yes | How many entrants a group of this stage seats. Null means no groups. |
| `group_advance` | INTEGER | yes | How many places of one group or one lobby play on. |
| `auto_advance` | BOOLEAN | no | On: scoring the last series of the stage seeds the next stage by itself. |
| `seeds_locked_at` | TIMESTAMP | yes | When an admin locked the seeds. A locked stage refuses a seed write. Null means unlocked. |
| `third_place` | BOOLEAN | no | On: a single elimination adds the series the beaten semi-finalists play. |
| `grand_final_modifier` | VARCHAR | no | What a double elimination final holds: `one` series, a `reset`, or `skip`. |
| `max_mmr_difference` | INTEGER | yes | The largest MMR difference a captain draft pairs inside, 1 or more. A `gnl` stage only; the write refuses it on any other format. Null on a `gnl` stage reads as 100, which is never written into the row. Answered on the stage read; no service reads it. |

# Keys and joins

Primary key `id`. Foreign key `event_id` to [event](event.md), cascade on delete. Unique constraint on (`event_id`, `position`). Pointed at by [event_round](event_round.md) `stage_id`.

# Rules

A stage split into groups merges at the next stage; a division never merges. The engine never branches on the event kind. See [events module](../../concepts/events-module.md).

`max_mmr_difference` is the only column the write refuses outside its format. The stage read answers it filled in on a `gnl` stage, so a client never carries the default of its own; every other format answers null.
