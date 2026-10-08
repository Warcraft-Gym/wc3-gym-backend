---
type: Data Model
title: organizer_request
description: One member's open request to become an organizer; an admin's approval or decline deletes it.
resource: ../../../../app/models/organizer.py
tags: [auth, events, data]
generated: { by: claude-code/claude-opus-5-5, at: 2026-10-05T18:00:00Z }
sources:
  - id: model
    resource: ../../../../app/models/organizer.py
    title: OrganizerRequest
  - id: service
    resource: ../../../../app/services/organizers.py
    title: request, requests, decline
---

# Schema

| Column | Type | Null | Meaning |
|---|---|---|---|
| `discord_id` | VARCHAR | no | Primary key. The Discord account that asks. |
| `name` | VARCHAR | no | The account's Discord name when it asked. |
| `note` | VARCHAR | yes | What the member wants to run, at most 300 characters. |
| `requested_at` | TIMESTAMP | no | When the request was sent. Set by the app. |

# Keys and joins

Primary key `discord_id`, so an account holds one open request. No foreign keys. `GET /organizers/requests` joins the [users](users.md) row by Discord id to name the player behind a request, when there is one.

# Rules

- A guild member sends one with `POST /organizers/requests`; a second send rewrites the note. An account that already holds a grant is refused with a 400.
- `/me` answers `organizer_request: "pending"` while the row exists.
- `POST /organizers/requests/{discord_id}/approve` writes the [organizer_grant](organizer_grant.md) and deletes the row; `…/decline` deletes it. Both are an admin's.
