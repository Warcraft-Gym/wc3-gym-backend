---
type: Data Model
title: user_busy
description: One one-off busy range of a player, as whole local days with both ends included; a soft hint like a weekly block.
resource: ../../../../app/models/user_block.py
tags: [auth, data]
generated: { by: claude-code/claude-fable-5-1, at: 2026-09-14T15:15:00Z }
verified: { by: process:test_okf, at: 2026-09-14T16:47:40Z }
sources:
  - id: model
    resource: ../../../../app/models/user_block.py
    title: UserBusy
  - id: blocks
    resource: ../../../../app/services/soft_blocks.py
    title: A player writes their own busy ranges
---

# Schema

| Column | Type | Null | Meaning |
|---|---|---|---|
| `id` | INTEGER | no | Primary key. |
| `user_id` | INTEGER | no | The player who owns the range. |
| `label` | VARCHAR | yes | A short free-text name the player gave the range. |
| `first_day` | DATE | no | The first busy day, local to the player. |
| `last_day` | DATE | no | The last busy day, included. Not before `first_day`. |
| `created_at` | TIMESTAMP | no | When the row was written. Set by the app. |
| `updated_at` | TIMESTAMP | no | When the row last changed. Set by the app on every update. |

# Keys and joins

Primary key `id`. Foreign key `user_id` to [users](users.md), cascade on delete. Check constraint `last_day >= first_day`. Index on (`user_id`, `last_day`).

# Rules

The same rules as [user_block](user_block.md): a hint, never a round answer. See [scheduling and availability](../../concepts/scheduling-and-availability.md).
