---
type: Data Model
title: announcement_subscriber
description: One member's choice about the cup announcements, subscribed to the role or declined, keyed by the Discord account the role is granted to; no row is no choice yet.
resource: ../../../../app/models/announcement.py
tags: [discord, data]
generated: { by: claude-code/claude-opus-5-5, at: 2026-10-25T18:00:00Z }
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
| `discord_id` | VARCHAR(50) | no | Primary key. The Discord account the choice is about. |
| `status` | VARCHAR(10) | no | `subscribed`: the member takes the role. `declined`: the member said no, from Home or from the question a cup sign-up asks, and is not asked again. `subscribed` by default. |
| `subscribed_at` | TIMESTAMPTZ | no | When the member first chose. |

# Keys and joins

Primary key `discord_id`. No foreign keys: the account is the one the session names, and a guild member needs no player row to take the role.

# Rules

- `PUT /me/announcements` with `subscribed` grants or takes back the role the `announcement_role_id` setting names, then writes the row as `subscribed` or `declined`; a row is never deleted, so leaving is a choice the sign-up question respects. The role is written first: when Discord refuses, the route answers 502 and the row stays as it was.
- `GET /me/announcements` answers `available`, `subscribed` and `ask`, true while the member has no row, which is when a cup sign-up asks. `available` is false while the `announcement_channel_id` or `announcement_role_id` setting is missing, and for a guest or the admin token, which hold no guild account.
- The operator binds the announcement role to no role kind, as [Discord setup](../../runbooks/discord-setup.md) says, so the role sync never takes it back. See [the decision](../../decisions/cup-announcements.md).
