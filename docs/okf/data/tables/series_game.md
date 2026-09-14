---
type: Data Model
title: series_game
description: One game of a series with the side that won it and the map it was played on, because a 2-1 score alone cannot say which.
resource: ../../../../app/models/series_game.py
tags: [events, data]
generated: { by: claude-code/claude-fable-5-1, at: 2026-09-14T15:15:00Z }
verified: { by: process:test_okf, at: 2026-09-14T16:47:40Z }
sources:
  - id: model
    resource: ../../../../app/models/series_game.py
    title: DBSeriesGame
  - id: games
    resource: ../../../../app/services/series_games.py
    title: The report writes the games with the result
---

# Schema

| Column | Type | Null | Meaning |
|---|---|---|---|
| `series_id` | INTEGER | no | The series. Part of the key. |
| `game_no` | INTEGER | no | The game number, from 1, in the order played. Part of the key. |
| `winner_side` | VARCHAR | no | `A` (player1) or `B` (player2). |
| `map_id` | INTEGER | yes | The map played. Null when nobody said which; the read then offers the map the rules name. |

# Keys and joins

Primary key (`series_id`, `game_no`). Foreign keys: `series_id` to [series](series.md), cascade; `map_id` to [maps](maps.md), set null.

# Rules

The two scores on the series stay the total; these rows say how it was reached. See [series reporting](../../concepts/series-reporting.md) and [the veto decision](../../decisions/veto-warns-never-blocks.md).
