---
type: Data Model
title: discord_role_hidden
description: One guild role an admin marked as none of the app's business, so the binding page hides it and it can never be bound.
resource: ../../../../app/models/discord_role_binding.py
tags: [schema, discord]
generated: { by: claude-code/claude-fable-5-1, at: 2026-09-14T15:15:00Z }
sources:
  - id: model
    resource: ../../../../app/models/discord_role_binding.py
    title: DiscordRoleHidden
  - id: config
    resource: ../../../../app/api/routes/config.py
    title: The hide and unhide routes
---

# Schema

| Column | Type | Null | Meaning |
|---|---|---|---|
| `discord_role` | VARCHAR | no | Primary key. The guild role id. |

# Keys and joins

Primary key `discord_role`. No foreign keys. Nothing points at this table.

# Rules

See [discord_role_binding](discord_role_binding.md).
