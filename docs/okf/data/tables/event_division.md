---
type: Data Model
title: event_division
description: One MMR band of an event that runs the whole stage list on its own and never merges; a KOTH bracket is a division.
resource: ../../../../app/models/event_division.py
tags: [events, data]
generated: { by: claude-code/claude-fable-5-1, at: 2026-09-14T15:15:00Z }
verified: { by: process:test_okf, at: 2026-09-14T16:47:40Z }
sources:
  - id: model
    resource: ../../../../app/models/event_division.py
    title: EventDivision
  - id: events
    resource: ../../../../app/services/events.py
    title: EventService.set_divisions and assign_divisions
  - id: cut
    resource: ../../../../app/core/divisions.py
    title: The cut by lower bound and size
---

# Schema

| Column | Type | Null | Meaning |
|---|---|---|---|
| `id` | INTEGER | no | Primary key. |
| `event_id` | INTEGER | no | The event the division belongs to. |
| `position` | INTEGER | no | The order divisions read in, the strongest first at 1. Unique per event. |
| `name` | VARCHAR | yes | A display name, such as a bracket name. |
| `lower_bound` | INTEGER | yes | The MMR the division opens at. Null while the bands are unset. |
| `size` | INTEGER | yes | How many entrants the division takes when the cut counts from the top. Null means no size cut. |

# Keys and joins

Primary key `id`. Foreign key `event_id` to [event](event.md), cascade on delete. Unique constraint on (`event_id`, `position`).

Pointed at by [event_entrant](event_entrant.md), [matches](matches.md) and [series](series.md) through `division_id`, all set null on delete.

# Rules

Replacing the division list clears every entrant's division and manual placement. See [events module](../../concepts/events-module.md).
