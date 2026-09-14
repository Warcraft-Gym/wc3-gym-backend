---
type: Data Model
title: user_block
description: One standing weekly block of a player, as local wall-clock times on a set of weekdays; a soft hint that informs scheduling and never constrains it.
resource: ../../../../app/models/user_block.py
tags: [schema, access]
generated: { by: claude-code/claude-fable-5-1, at: 2026-09-14T15:15:00Z }
sources:
  - id: model
    resource: ../../../../app/models/user_block.py
    title: UserBlock
  - id: blocks
    resource: ../../../../app/services/soft_blocks.py
    title: A player writes their own blocks
  - id: free-time
    resource: ../../../../app/core/free_time.py
    title: Resolves the local times to UTC intervals
---

# Schema

| Column | Type | Null | Meaning |
|---|---|---|---|
| `id` | INTEGER | no | Primary key. |
| `user_id` | INTEGER | no | The player who owns the block. |
| `label` | VARCHAR | yes | A short free-text name the player gave the block. |
| `weekdays` | SMALLINT | no | ISO weekday bits: Monday 1, Tuesday 2, up to Sunday 64. Between 1 and 127. |
| `start_local` | TIME | no | Start of the block in the player's `users.timezone`. |
| `end_local` | TIME | no | End of the block, local. An end before the start runs past midnight into the next day. |
| `created_at` | TIMESTAMP | no | When the row was written. Set by the app. |
| `updated_at` | TIMESTAMP | no | When the row last changed. Set by the app on every update. |

# Keys and joins

Primary key `id`. Foreign key `user_id` to [users](users.md), cascade on delete. Check constraints: `weekdays BETWEEN 1 AND 127`; `end_local <> start_local`.

# Rules

A block never writes a [round_availability](round_availability.md) row. Local time and zone are stored, never a UTC mask, so daylight saving does not shift the block. See [scheduling and availability](../../concepts/scheduling-and-availability.md) and [the decision](../../decisions/availability-blocklist.md).
