---
type: Data Model
title: admin_grant
description: One Discord account that administers the site, granted on the Config page; the bootstrap ids in ADMIN_DISCORD_IDS need no row.
resource: ../../../../app/models/admin_grant.py
tags: [schema, access]
generated: { by: claude-code/claude-fable-5-1, at: 2026-09-14T15:15:00Z }
sources:
  - id: model
    resource: ../../../../app/models/admin_grant.py
    title: AdminGrant
  - id: admins
    resource: ../../../../app/services/admins.py
    title: grant and revoke
---

# Schema

| Column | Type | Null | Meaning |
|---|---|---|---|
| `discord_id` | VARCHAR | no | Primary key. The Discord account id that is admin. |
| `name` | VARCHAR | no | The display name of the account when the grant was made. Empty string when unknown. |
| `granted_by` | VARCHAR | no | The Discord id of the granting account, or `admin` for the token login. |
| `granted_at` | TIMESTAMP | no | When the grant was made. Set by the app. |

# Keys and joins

Primary key `discord_id`. No foreign keys: an id may be granted before a player row exists.

# Rules

An id in `ADMIN_DISCORD_IDS` is admin without a row and cannot be revoked. Discord grants nothing. See [roles and permissions](../../concepts/roles-and-permissions.md).
