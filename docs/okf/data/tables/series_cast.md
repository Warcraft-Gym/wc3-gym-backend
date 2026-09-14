---
type: Data Model
title: series_cast
description: One member's claim to cast one series, with the channel it streams on and the VOD pasted after; planned, live and VOD states derive at read time.
resource: ../../../../app/models/series_cast.py
tags: [events, data]
generated: { by: claude-code/claude-fable-5-1, at: 2026-09-14T15:15:00Z }
verified: { by: process:test_okf, at: 2026-09-14T16:47:40Z }
sources:
  - id: model
    resource: ../../../../app/models/series_cast.py
    title: SeriesCast
  - id: casts
    resource: ../../../../app/services/casts.py
    title: claim, change, remove, set the VOD
---

# Schema

| Column | Type | Null | Meaning |
|---|---|---|---|
| `id` | INTEGER | no | Primary key. |
| `series_id` | INTEGER | no | The series claimed. |
| `user_id` | INTEGER | yes | The member who claimed it. Null for a cast the importer or an admin entered, which only an admin edits. |
| `channel_url` | VARCHAR | no | A Twitch or YouTube channel link. |
| `vod_url` | VARCHAR | yes | The recording, a Twitch video or a YouTube watch, live or short link. Null when none was pasted. |
| `vod_added_at` | TIMESTAMP | yes | When the VOD was pasted. Kept because a Twitch VOD expires. |
| `created_at` | TIMESTAMP | no | When the claim was made. Set by the app. |

# Keys and joins

Primary key `id`. Foreign keys: `series_id` to [series](series.md), cascade; `user_id` to [users](users.md), set null. Unique constraint on (`series_id`, `user_id`).

# Rules

A series with a result takes no claim. A channel link that is itself a video reads as the VOD once the series is over; nothing stores that. See [series reporting](../../concepts/series-reporting.md).
