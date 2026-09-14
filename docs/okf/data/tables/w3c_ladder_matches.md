---
type: Data Model
title: w3c_ladder_matches
description: One ranked 1v1 W3Champions match of one GNL player, with the selected and the played race on both sides; points and badges derive from it.
resource: ../../../../app/models/w3c_ladder_match.py
tags: [w3champions, data]
generated: { by: claude-code/claude-fable-5-1, at: 2026-09-14T15:15:00Z }
verified: { by: process:test_okf, at: 2026-09-14T16:47:40Z }
sources:
  - id: model
    resource: ../../../../app/models/w3c_ladder_match.py
    title: W3CLadderMatch
  - id: ladder
    resource: ../../../../app/services/ladder.py
    title: The match sync inserts the rows a player has no row for yet
---

# Schema

| Column | Type | Null | Meaning |
|---|---|---|---|
| `id` | INTEGER | no | Primary key. |
| `user_id` | INTEGER | no | The GNL player the row belongs to. |
| `w3c_match_id` | VARCHAR | no | The W3Champions match id. One row per player per match. |
| `wc3_season` | INTEGER | no | The W3Champions season number. |
| `start_time` | TIMESTAMP | no | When the match started, UTC. |
| `duration_s` | INTEGER | no | Length in seconds. A match of `MIN_DURATION_S` or less pays nothing. |
| `map_name` | VARCHAR | yes | The map, as W3Champions names it. |
| `race` | VARCHAR | yes | The race the player selected; `RANDOM` when they picked random. |
| `played_race` | VARCHAR | yes | The race the player played, a random pick resolved to what it rolled. |
| `opp_battletag` | VARCHAR | yes | The opponent's battle tag. |
| `opp_race` | VARCHAR | yes | The race the opponent selected. |
| `opp_played_race` | VARCHAR | yes | The race the opponent played. |
| `won` | BOOLEAN | no | Whether the player won. |
| `mmr_before` | INTEGER | yes | MMR before the match. Null on a placement match, which is unrated. |
| `mmr_after` | INTEGER | yes | MMR after the match. Null the same way. |

# Keys and joins

Primary key `id`. Foreign key `user_id` to [users](users.md). Unique index on (`w3c_match_id`, `user_id`). Index on (`user_id`, `start_time`).

# Rules

Both races are stored per side because the W3Champions search filters on the selected race and Random counts everything. A player scores only on their signup race; the filter belongs in the read. A read takes one season window. See [ladder and achievements](../../concepts/ladder-and-achievements.md) and [the pitfall](../../pitfalls/ladder-egress.md).
