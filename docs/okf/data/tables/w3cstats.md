---
type: Data Model
title: w3cstats
description: One player's 1v1 record on W3Champions for one race in one W3Champions season, as the stats sync last read it.
resource: ../../../../app/models/w3c_stats.py
tags: [w3champions, data]
generated: { by: claude-code/claude-fable-5-1, at: 2026-09-14T15:15:00Z }
verified: { by: process:test_okf, at: 2026-09-14T17:40:50Z }
sources:
  - id: model
    resource: ../../../../app/models/w3c_stats.py
    title: W3CStats
  - id: users
    resource: ../../../../app/services/users.py
    title: update_w3c_stats replaces the rows
  - id: client
    resource: ../../../../app/services/w3c.py
    title: The client reads the player stats
---

# Schema

| Column | Type | Null | Meaning |
|---|---|---|---|
| `id` | INTEGER | no | Primary key. |
| `user_id` | INTEGER | no | The player. |
| `race` | VARCHAR | yes | The race the record is for: `RANDOM`, `HU`, `OC`, `NE`, `UD`. |
| `wc3_season` | INTEGER | no | The W3Champions season number. |
| `wins` | INTEGER | yes | Wins that season on that race. |
| `losses` | INTEGER | yes | Losses. |
| `games` | INTEGER | yes | Games played. |
| `mmr` | INTEGER | yes | The MMR. The entrant and draft board reads and the series rows of a running event take it from the row of the signup race and the pinned season. |
| `winrate` | FLOAT | yes | Wins over games, as W3Champions reports it. |
| `league` | INTEGER | yes | The W3Champions league order the player sits in, as the client reads `leagueOrder`. |

# Keys and joins

Primary key `id`. Foreign key `user_id` to [users](users.md). Unique index on (`user_id`, `race`, `wc3_season`).

# Rules

Only the 1v1 game mode is stored. The season the reads take is the `current_w3c_season` setting. `users.w3c_synced_at` stamps the sync. See [W3Champions](../../concepts/w3champions.md) and [the season pin decision](../../decisions/season-boundary-manual.md).
