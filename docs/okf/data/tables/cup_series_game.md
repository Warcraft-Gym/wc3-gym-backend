---
type: Data Model
title: cup_series_game
description: One game of a cup series with the side that won it and the map it was played on.
resource: ../../../../app/models/cup_series.py
tags: [events, series, data]
generated: { by: claude-code/claude-opus-5-5, at: 2026-10-12T21:00:00Z }
sources:
  - id: model
    resource: ../../../../app/models/cup_series.py
    title: CupSeriesGame
  - id: service
    resource: ../../../../app/services/cup_series.py
    title: report and games
---

# Schema

| Column | Type | Null | Meaning |
|---|---|---|---|
| `series_id` | INTEGER | no | The cup series. Part of the key. |
| `game_no` | INTEGER | no | The game number, from 1, in play order. Part of the key. |
| `winner_side` | VARCHAR(1) | yes | `A` (side 1) or `B` (side 2). |
| `map_id` | INTEGER | yes | The map the game was played on. Null when nobody named it. |

# Keys and joins

Primary key (`series_id`, `game_no`). Foreign keys: `series_id` to [cup_series](cup_series.md), cascade; `map_id` to [maps](maps.md), set null.

# Rules

`PUT /cup-series/{id}/report` writes the games with the result, checked against the score, and replaces the games stored before. A cleared result deletes them. `GET /cup-series/{id}/games` answers them with the map the veto offers each game when the cup vetoes by best-of.
