---
type: Data Model
title: event_award
description: One place of a finished event, frozen from the table of its last stage when an admin closes it; a trophy read lists these rows.
resource: ../../../../app/models/event_award.py
tags: [events, data]
generated: { by: claude-code/claude-fable-5-1, at: 2026-09-26T04:00:00Z }
verified: { by: process:test_okf, at: 2026-09-14T17:40:50Z }
sources:
  - id: model
    resource: ../../../../app/models/event_award.py
    title: EventAward
  - id: awards
    resource: ../../../../app/services/awards.py
    title: close_event writes the whole list
---

# Schema

| Column | Type | Null | Meaning |
|---|---|---|---|
| `id` | INTEGER | no | Primary key. |
| `event_id` | INTEGER | no | The event that paid the place. |
| `entrant_id` | INTEGER | yes | The entrant that took it. Null once the entrant row is deleted. |
| `user_id` | INTEGER | yes | The player behind the entrant, on a solo event. |
| `team_id` | INTEGER | yes | The team behind the entrant, on a team event. |
| `place` | INTEGER | yes | The place, from 1. Null for a title that ranks nobody. |
| `title` | VARCHAR | no | What the award prints: `Champion`, `Runner-up`, `Third`, else `Placed N`. |
| `awarded_at` | TIMESTAMP | yes | When the award was made. Null when the archival source gives no instant. |

# Keys and joins

Primary key `id`. Foreign keys: `event_id` to [event](event.md), cascade; `entrant_id` to [event_entrant](event_entrant.md), set null; `user_id` to [users](users.md), cascade; `team_id` to [teams](teams.md), cascade.

# Rules

For live events, `POST /events/{id}/finish` deletes the event's rows and writes one per placed entrant of every division, so a second close rewrites and never doubles. See [events module](../../concepts/events-module.md).

Finishing an imported historical event preserves its source awards. Crown identities remain unresolved independently of the pairings.
