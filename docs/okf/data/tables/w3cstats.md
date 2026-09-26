---
type: Data Model
title: w3cstats
description: One player's 1v1 record on W3Champions for one race in one W3Champions season, as the stats sync last read it.
resource: ../../../../app/models/w3c_stats.py
tags: [w3champions, data]
generated: { by: claude-code/claude-opus-5-5, at: 2026-09-26T12:00:00Z }
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
  - id: summary
    resource: ../../../../app/services/w3c_stats.py
    title: The live window and the ladder summary
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
| `mmr` | INTEGER | yes | The MMR. The entrant and draft board reads and the series rows of a running event take the newest live window row of the signup race that carries one. |
| `winrate` | FLOAT | yes | Wins over games, as W3Champions reports it. |
| `league` | INTEGER | yes | The W3Champions league order the player sits in, as the client reads `leagueOrder`. |

# Keys and joins

Primary key `id`. Foreign key `user_id` to [users](users.md). Unique index on (`user_id`, `race`, `wc3_season`).

# Rules

Only the 1v1 game mode is stored. The season the reads take is the `current_w3c_season` setting, else the newest stored season. `users.w3c_synced_at` stamps the sync.

The live window is that season and the one before it (`app/services/w3c_stats.py`). Eligibility, the entrant and draft board ratings, the series rows of a running event, the fantasy seeding and the Discord series cards read the window alone: the rating is the newest window row with an MMR on the race, the games are the sum of the window rows (`min_games_seasons` of 1 counts the current season alone). List reads load only the window rows.

A user payload carries the summary the backend derives from the rows its read loaded, never the rows: `w3c_stats` on the user models is left out of every answer. `race_mmrs` holds one entry per race: the `mmr`, `wins`, `losses` and `wc3_season` of the newest window row with a rating, else of the newest window row, and the window's `games`, window races by MMR, highest first. `main_race` is the window race with the top MMR among those with 10 or more window games, else null. `GET /users/{key}` also lists a race with no window row from its newest older row, `stale` true, after the window races, newest season first. See [W3Champions](../../concepts/w3champions.md) and [the season pin decision](../../decisions/season-boundary-manual.md).
