---
type: Data Model
title: series_replay
description: One replay slot per game of a series, holding the object key of the file in the replay bucket and who uploaded it.
resource: ../../../../app/models/series_replay.py
tags: [events, data]
generated: { by: claude-code/claude-fable-5-1, at: 2026-09-14T15:15:00Z }
verified: { by: process:test_okf, at: 2026-09-14T16:47:40Z }
sources:
  - id: model
    resource: ../../../../app/models/series_replay.py
    title: DBSeriesReplay
  - id: replays
    resource: ../../../../app/services/replays.py
    title: A slot is written once the file is in the bucket
---

# Schema

| Column | Type | Null | Meaning |
|---|---|---|---|
| `series_id` | INTEGER | no | The series. Part of the key. |
| `game_no` | INTEGER | no | The game the replay belongs to, from 1. Part of the key. |
| `key` | VARCHAR | no | The object key in the bucket. Starts with the deployment environment. |
| `uploaded_by` | INTEGER | yes | The player who uploaded the file. Null once that player row is deleted. |
| `uploaded_at` | TIMESTAMP | no | When the slot was written. Set by the app. |

# Keys and joins

Primary key (`series_id`, `game_no`). Foreign keys: `series_id` to [series](series.md), cascade; `uploaded_by` to [users](users.md), set null.

# Rules

No bytes are stored. The payload answers a presigned download URL built from `key`, never the key itself. A later upload lands on the same key. A deleted series drops its files after the commit. See [pictures and replays](../../concepts/pictures-and-replays.md).
