---
type: Data Model
title: event_organizer
description: One Discord account that runs one event beside the admins, the organizer that created it or a co-organizer it added.
resource: ../../../../app/models/organizer.py
tags: [auth, events, data]
generated: { by: claude-code/claude-opus-5-5, at: 2026-10-05T18:00:00Z }
sources:
  - id: model
    resource: ../../../../app/models/organizer.py
    title: EventOrganizer
  - id: service
    resource: ../../../../app/services/organizers.py
    title: runs, add_to_event, remove_from_event
---

# Schema

| Column | Type | Null | Meaning |
|---|---|---|---|
| `event_id` | INTEGER | no | The event run. Part of the primary key. |
| `discord_id` | VARCHAR | no | The Discord account that runs it. Part of the primary key. |
| `name` | VARCHAR | no | The name to show: the name sent with the add, else the player row's, else the grant's. |
| `added_by` | VARCHAR | no | The Discord id of whoever added the row, or `admin` for the token login. |
| `added_at` | TIMESTAMP | no | When the row was written. Set by the app. |

# Keys and joins

Primary key (`event_id`, `discord_id`). Foreign key: `event_id` to [event](event.md), cascade. Index on `discord_id`. Keyed by Discord account, not by player row, so an organizer needs no player row.

# Rules

- `POST /events` by an organizer writes the creator's row. An admin's small event writes the admin's row too; the GNL creation path writes none, and a KOTH night is opened by its own route, so neither kind ever holds a row.
- A runner of the event adds and removes rows with `POST /events/{id}/organizers` and `DELETE /events/{id}/organizers/{discord_id}`. `GET /events/{id}/organizers` is an open read.
- A row lets its account run the event while the account is a guild member acting as itself, whether or not it still holds an [organizer_grant](organizer_grant.md). See [roles and permissions](../../concepts/roles-and-permissions.md#organizers).
