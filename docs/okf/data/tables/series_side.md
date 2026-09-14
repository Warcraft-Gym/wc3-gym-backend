---
type: Data Model
title: series_side
description: "One seat of a series that is not a plain 1v1: a player in an FFA lobby or on a team side, with the place that side finished."
resource: ../../../../app/models/series_side.py
tags: [events, data]
generated: { by: claude-code/claude-fable-5-1, at: 2026-09-14T15:15:00Z }
verified: { by: process:test_okf, at: 2026-09-14T17:40:50Z }
sources:
  - id: model
    resource: ../../../../app/models/series_side.py
    title: SeriesSide
  - id: engine
    resource: ../../../../app/services/stage_engine.py
    title: set_places, set_sides and the lobby seat writes
---

# Schema

| Column | Type | Null | Meaning |
|---|---|---|---|
| `series_id` | INTEGER | no | The series the seat belongs to. Part of the key. |
| `side_no` | INTEGER | no | Which side the seat plays. An FFA lobby seats one player per side. Part of the key. |
| `user_id` | INTEGER | no | The player in the seat. 0 means the seat names no player yet. Part of the key; no foreign key. |
| `entrant_id` | INTEGER | yes | The entrant behind the seat. |
| `place` | INTEGER | yes | Where the side finished, from 1. Repeated on every row of one side. Null before the result. |

# Keys and joins

Primary key (`series_id`, `side_no`, `user_id`). Foreign keys: `series_id` to [series](series.md), cascade; `entrant_id` to [event_entrant](event_entrant.md), set null. Index on `user_id`.

# Rules

A 1v1 series writes no row here, so every GNL read keeps its shape. An organiser seats a lobby before the round starts; a captain writes the roster of a fixture side. See [events module](../../concepts/events-module.md).
