---
type: Data Model
title: announcement_subscriber
description: One member who takes the cup announcement role, keyed by the Discord account the role is granted to.
resource: ../../../../app/models/announcement.py
tags: [discord, data]
generated: { by: claude-code/claude-opus-5-5, at: 2026-10-15T19:00:00Z }
sources:
  - id: model
    resource: ../../../../app/models/announcement.py
    title: AnnouncementSubscriber
  - id: service
    resource: ../../../../app/services/cup_announcements.py
    title: The cup announcements and the Home switch
---

# Schema

| Column | Type | Null | Meaning |
|---|---|---|---|
| `discord_id` | VARCHAR(50) | no | Primary key. The Discord account that takes the role. |
| `subscribed_at` | TIMESTAMPTZ | no | When the member turned the switch on. |

# Keys and joins

Primary key `discord_id`. No foreign keys: the account is the one the session names, and a guild member needs no player row to take the role.

# Rules

- `PUT /me/announcements` with `subscribed` grants or takes back the role the `announcement_role_id` setting names, then writes or deletes the row. The role is written first: when Discord refuses, the route answers 502 and the row stays as it was.
- `GET /me/announcements` answers `available` and `subscribed`. `available` is false while the `announcement_channel_id` or `announcement_role_id` setting is missing, and for a guest or the admin token, which hold no guild account.
- No role binding names the announcement role, so the role sync never takes it back. See [the decision](../../decisions/cup-announcements.md).
