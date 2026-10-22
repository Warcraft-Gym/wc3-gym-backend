---
type: Data Model
title: discord_post
description: One card the app posted in Discord and may edit later, with the two stamps that pace edits to the channel's rate limit.
resource: ../../../../app/models/discord_post.py
tags: [discord, data]
generated: { by: claude-code/claude-opus-5-5, at: 2026-10-22T07:56:14Z }
verified: { by: process:test_okf, at: 2026-09-14T17:40:50Z }
sources:
  - id: model
    resource: ../../../../app/models/discord_post.py
    title: DiscordPost
  - id: posts
    resource: ../../../../app/services/discord_posts.py
    title: remember, refresh_series and wait_for_channel
  - id: cup-announcements
    resource: ../../../../app/services/cup_announcements.py
    title: A cup's announcements, and the rows a deleted cup drops
---

# Schema

| Column | Type | Null | Meaning |
|---|---|---|---|
| `id` | INTEGER | no | Primary key. |
| `kind` | VARCHAR | no | Which card built the post: `veto`, `announce`, `result`, `result_change` (the note that a reported result changed), `cast`, `reminder` or `event`; a cup's announcements are `cup_open`, `cup_remind`, `cup_leg_remind`, `cup_draw`, `cup_round` and `cup_result`. |
| `subject_id` | INTEGER | no | The id of the row the card is about: the event for `event`, `cup_open`, `cup_remind` and `cup_result`, the round of a cup played over rounds (`cup_leg`) for `cup_leg_remind`, the stage for `cup_draw`, the stage's round (`event_round`) for `cup_round`, and a series for every other kind. |
| `channel_id` | VARCHAR | no | The Discord channel the card is in. |
| `message_id` | VARCHAR | no | The Discord message id. Unique. |
| `changed_at` | TIMESTAMP | yes | When the subject last changed. An edit is due while it is after `edited_at`. |
| `edited_at` | TIMESTAMP | yes | When the card was last posted or edited. The channel's next write waits a second after the latest one. |

# Keys and joins

Primary key `id`. No foreign keys. Unique constraint on `message_id`. Index on (`kind`, `subject_id`).

# Rules

An edit is claimed with one UPDATE, so a burst of writes collapses to the last state and no process holds a lock. A `result_change` row is never edited or deleted: it records one change, and the row keeps the channel's pacing. The event card's message id is also in [event](event.md) `discord_event_id`. A deleted cup takes the rows about it, its stages, its rounds and its event card; the messages stay in the channel, and nothing edits them again. See [Discord integration](../../concepts/discord-integration.md) and [the decision](../../decisions/discord-rate-limit.md).
