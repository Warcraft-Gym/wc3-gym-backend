---
type: Data Model
title: discord_role_binding
description: One binding of a role kind and scope to a guild role, so the sync can grant and take back that role from what the database says.
resource: ../../../../app/models/discord_role_binding.py
tags: [schema, discord]
generated: { by: claude-code/claude-fable-5-1, at: 2026-09-14T15:15:00Z }
sources:
  - id: model
    resource: ../../../../app/models/discord_role_binding.py
    title: DiscordRoleBinding
  - id: roles
    resource: ../../../../app/services/discord_roles.py
    title: The sync reads every binding marked synced
  - id: config
    resource: ../../../../app/api/routes/config.py
    title: The binding routes
---

# Schema

| Column | Type | Null | Meaning |
|---|---|---|---|
| `id` | INTEGER | no | Primary key. |
| `kind` | VARCHAR | no | What earns the role: `admin`, `captain`, `team`, `fantasy`, `gnl_participant` or `champion`. An `admin` binding is never synced. |
| `scope` | VARCHAR | no | Which seasons the binding reads: `current`, `season` or `all`. |
| `season_id` | INTEGER | yes | The season a `season`-scoped binding reads. A `champion` binding always names one. |
| `team_id` | INTEGER | yes | The team a `team` binding is for. Null on the other kinds. |
| `discord_role` | VARCHAR | no | The guild role id. Unique: one role belongs to one binding. |
| `synced` | BOOLEAN | no | On: the sync manages the role. Off: the binding is recorded and the guild role is left alone. |

# Keys and joins

Primary key `id`. Foreign keys: `season_id` to [event](event.md), cascade; `team_id` to [teams](teams.md), cascade. Unique index on `discord_role`.

# Rules

The database is the source and the guild is a mirror; the sync runs on a button press and never touches a role no binding names. A role in [discord_role_hidden](discord_role_hidden.md) cannot be bound. See [roles and permissions](../../concepts/roles-and-permissions.md) and [the decision](../../decisions/app-managed-roles.md).
