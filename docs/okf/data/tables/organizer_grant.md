---
type: Data Model
title: organizer_grant
description: One Discord account that may create small events, granted by an admin directly or by approving the account's request.
resource: ../../../../app/models/organizer.py
tags: [auth, events, data]
generated: { by: claude-code/claude-opus-5-5, at: 2026-10-05T18:00:00Z }
sources:
  - id: model
    resource: ../../../../app/models/organizer.py
    title: OrganizerGrant
  - id: service
    resource: ../../../../app/services/organizers.py
    title: grant, revoke and standing
---

# Schema

| Column | Type | Null | Meaning |
|---|---|---|---|
| `discord_id` | VARCHAR | no | Primary key. The Discord account id that organizes. |
| `name` | VARCHAR | no | The name to show: the player row's, else the name the request carried. Empty string when unknown. |
| `granted_by` | VARCHAR | no | The Discord id of the granting admin, or `admin` for the token login. |
| `granted_at` | TIMESTAMP | no | When the grant was made. Set by the app. |

# Keys and joins

Primary key `discord_id`. No foreign keys: an organizer needs no player row, only a Discord login.

# Rules

- A grant counts only while the account is a member of the guild and acts as itself. A guest, and an admin viewing as a lower role, hold no organizer rights. See [roles and permissions](../../concepts/roles-and-permissions.md#organizers).
- `GET`, `POST /organizers` and `DELETE /organizers/{discord_id}` are an admin's. A grant closes the account's [organizer_request](organizer_request.md).
- A grant lets the account create events. Running one event is the [event_organizer](event_organizer.md) row, which a revoke leaves in place.
