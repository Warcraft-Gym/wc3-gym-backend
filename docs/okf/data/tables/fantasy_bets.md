---
type: Data Model
title: fantasy_bets
description: One stake of points a member placed on one series and the player they called to win it.
resource: ../../../../app/models/fantasy_bet.py
tags: [fantasy, data]
generated: { by: claude-code/claude-fable-5-1, at: 2026-09-14T15:15:00Z }
verified: { by: process:test_okf, at: 2026-09-14T17:40:50Z }
sources:
  - id: model
    resource: ../../../../app/models/fantasy_bet.py
    title: FantasyBet
  - id: service
    resource: ../../../../app/services/fantasy_bets.py
    title: FantasyBetService
---

# Schema

| Column | Type | Null | Meaning |
|---|---|---|---|
| `id` | INTEGER | no | Primary key. |
| `season_id` | INTEGER | no | The season the bet counts in. |
| `series_id` | INTEGER | no | The series bet on. |
| `user_id` | INTEGER | no | The member who placed the bet. One bet per member per series. |
| `winner_id` | INTEGER | no | The player called to win. |
| `bet_points` | INTEGER | no | The stake. Added when the call was right, subtracted when it was wrong. |

# Keys and joins

Primary key `id`. Foreign keys: `season_id` to [event](event.md), cascade; `series_id` to [series](series.md), cascade; `user_id` and `winner_id` to [users](users.md), cascade. Unique index on (`series_id`, `user_id`).

# Rules

The result of a bet costs no statement: the series scores already ride in the response. See [fantasy](../../concepts/fantasy.md).
