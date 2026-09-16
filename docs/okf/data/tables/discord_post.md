---
type: Data Model
title: discord_post
description: One card the app posted in Discord and may edit later, with the two stamps that pace edits to the channel's rate limit.
resource: ../../../../app/models/discord_post.py
tags: [discord, data]
generated: { by: claude-code/claude-fable-5-1, at: 2026-09-14T15:15:00Z }
verified: { by: process:test_okf, at: 2026-09-14T17:40:50Z }
sources:
  - id: model
    resource: ../../../../app/models/discord_post.py
    title: DiscordPost
  - id: posts
    resource: ../../../../app/services/discord_posts.py
    title: remember, refresh_series and wait_for_channel
---

# Schema

| Column | Type | Null | Meaning |
|---|---|---|---|
| `id` | INTEGER | no | Primary key. |
| `kind` | VARCHAR | no | Which card built the post: `veto`, `announce`, the result card, the cast claim card or the reminder. |
| `subject_id` | INTEGER | no | The id of the row the card is about, a series for every kind. |
| `channel_id` | VARCHAR | no | The Discord channel the card is in. |
| `message_id` | VARCHAR | no | The Discord message id. Unique. |
| `changed_at` | TIMESTAMP | yes | When the subject last changed. An edit is due while it is after `edited_at`. |
| `edited_at` | TIMESTAMP | yes | When the card was last posted or edited. The channel's next write waits a second after the latest one. |

# Keys and joins

Primary key `id`. No foreign keys. Unique constraint on `message_id`. Index on (`kind`, `subject_id`).

# Rules

An edit is claimed with one UPDATE, so a burst of writes collapses to the last state and no process holds a lock. The event card is not here: [event](event.md) `discord_event_id` holds its message id. See [Discord integration](../../concepts/discord-integration.md) and [the decision](../../decisions/discord-rate-limit.md).
