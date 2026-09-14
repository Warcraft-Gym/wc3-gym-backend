---
type: Data Model
title: event_round
description: One round of a stage: its number, its date window and the fixed map of game 1; a GNL playday is a round.
resource: ../../../../app/models/relationships.py
tags: [schema, events]
generated: { by: claude-code/claude-fable-5-1, at: 2026-09-14T15:15:00Z }
sources:
  - id: model
    resource: ../../../../app/models/relationships.py
    title: DBEventRound
  - id: seasons
    resource: ../../../../app/services/seasons.py
    title: fill_rounds and set_round write the GNL rounds
  - id: engine
    resource: ../../../../app/services/stage_engine.py
    title: generate and generate_next_round write the bracket rounds
---

# Schema

| Column | Type | Null | Meaning |
|---|---|---|---|
| `id` | INTEGER | no | Primary key. |
| `stage_id` | INTEGER | yes | The stage the round belongs to. Null on a row written before the stage existed. |
| `season_id` | INTEGER | no | The event the round belongs to. Kept beside `stage_id` so the GNL reads stay one select. |
| `number` | INTEGER | no | The place of the round in its stage. The GNL playday. Unique per event. |
| `name` | VARCHAR | yes | A display name. The engine writes `Final`, `Semifinals`, `Round of 16` or `Round N`; a GNL round has none. |
| `start_date` | DATE | yes | First day of the window. A round with no start date cannot be checked into. |
| `end_date` | DATE | yes | Last day of the window. Null means a one-day round. |
| `map_id` | INTEGER | yes | The map a `fixed` rule offers for game 1. |
| `best_of` | INTEGER | yes | Overrides the stage's `best_of` for this round. Null follows the stage. |

# Keys and joins

Primary key `id`. Foreign keys: `stage_id` to [event_stage](event_stage.md), cascade on delete; `season_id` to [event](event.md); `map_id` to [maps](maps.md), set null on delete. Unique constraint on (`season_id`, `number`).

Pointed at by [matches](matches.md), [series](series.md) and [round_availability](round_availability.md) through `round_id`.

# Rules

Nothing stores the round count; these rows are it. A GNL round is placed a week after the one before it when the season has a start date. Dropping a round drops its availability answers. See [GNL season](../../concepts/gnl-season.md) and [scheduling and availability](../../concepts/scheduling-and-availability.md).
