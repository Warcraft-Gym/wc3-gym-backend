---
type: Data Model
title: map_season
description: One map in one event's pool, with its place in the pool order.
resource: ../../../../app/models/relationships.py
tags: [maps, data]
generated: { by: claude-code/claude-fable-5-1, at: 2026-09-14T15:15:00Z }
verified: { by: process:test_okf, at: 2026-09-14T17:40:50Z }
sources:
  - id: model
    resource: ../../../../app/models/relationships.py
    title: DBMapSeason
  - id: seasons
    resource: ../../../../app/services/seasons.py
    title: add_maps, remove_maps, set_map_order, import_ladder_maps
---

# Schema

| Column | Type | Null | Meaning |
|---|---|---|---|
| `map_id` | INTEGER | no | The map. Part of the key. |
| `season_id` | INTEGER | no | The event. Part of the key. |
| `position` | INTEGER | no | The place in the pool, from 0. A new map is appended at the end. |

# Keys and joins

Primary key (`map_id`, `season_id`). Foreign keys: `map_id` to [maps](maps.md); `season_id` to [event](event.md).

# Rules

The pool is what the veto board offers. See [series reporting](../../concepts/series-reporting.md).
