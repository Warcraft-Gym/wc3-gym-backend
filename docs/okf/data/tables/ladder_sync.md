---
type: Data Model
title: ladder_sync
description: The ledger of the match sync: one row per player per W3Champions season saying when it was read, from when, and whether the read reached the end.
resource: ../../../../app/models/ladder_sync.py
tags: [schema, w3champions]
generated: { by: claude-code/claude-fable-5-1, at: 2026-09-14T15:15:00Z }
sources:
  - id: model
    resource: ../../../../app/models/ladder_sync.py
    title: LadderSync
  - id: ladder
    resource: ../../../../app/services/ladder.py
    title: _stamp writes the row after every chunk
---

# Schema

| Column | Type | Null | Meaning |
|---|---|---|---|
| `id` | INTEGER | no | Primary key. |
| `user_id` | INTEGER | no | The player. |
| `wc3_season` | INTEGER | no | The W3Champions season number. |
| `synced_at` | TIMESTAMP | no | When the pair was last read. |
| `complete` | BOOLEAN | no | On: the season was paged to its end, or past the window it was read for. A closed season marked complete is never asked for again. |
| `read_from` | TIMESTAMP | yes | The earliest instant any run read the season from. Only moved earlier. Null on a row older than the column. |

# Keys and joins

Primary key `id`. Foreign key `user_id` to [users](users.md). Unique index on (`user_id`, `wc3_season`).

# Rules

The open season is re-read from its own stamp. The season and team "last synced" stamps derive as the earliest stamp across the roster. `users.ladder_synced_at` is the per-player stamp. See [ladder and achievements](../../concepts/ladder-and-achievements.md).
