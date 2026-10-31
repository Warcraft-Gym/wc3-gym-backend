---
type: Data Model
title: cup_entrant_line
description: A cup entrant's place in the cup's line, the order the cup lets its sign-ups in, and whether a runner let it in by hand.
resource: ../../../../app/models/cup_settings.py
tags: [events, data]
generated: { by: claude-code/claude-opus-5-5, at: 2026-10-27T12:00:00Z }
sources:
  - id: model
    resource: ../../../../app/models/cup_settings.py
    title: CupEntrantLine
  - id: rules
    resource: ../../../../app/services/cup_waitlist.py
    title: A cup's line and its waitlist
  - id: places
    resource: ../../../../app/core/waitlist.py
    title: How many of the line are in
---

# Schema

| Column | Type | Null | Meaning |
|---|---|---|---|
| `entrant_id` | INTEGER | no | Primary key. The cup's entrant. |
| `joined_at` | TIMESTAMP | no | When the entrant last signed up: its place in the line. A return signup stands at the end, and a swap's new entrant takes the old one's place. |
| `held_in` | BOOLEAN | no | On: a runner let the entrant in by hand, with an admit or a swap, so the line never sends it back to the waitlist. Defaults to false. |

# Keys and joins

Primary key `entrant_id`, a foreign key to [event_entrant](event_entrant.md), `ON DELETE CASCADE`.

# Rules

- Every cup signup and every runner's hand-add writes the row. An entrant without one stands at its `event_entrant.created_at`.
- The line counts the entrants that have not withdrawn, in `joined_at` order. The first places are in and the rest wait on the waitlist (`event_entrant.waitlisted_at`). The places are the cup's `entrant_cap`, or every entrant without a cap. On a cup with divisions the cap counts one division: the line takes the first division as it fills, then each further division once it is filled completely.
- An entrant `held_in` is in whatever its place, and counts in the line.
- Until the cup is drawn the line moves both ways after each signup, withdrawal, removal and edit of the cap or of the divisions switch. Once a cup over rounds holds a draw the line only moves forward. A cup played on one evening is set at its draw.
- The row is a cup's alone, so no GNL or KOTH read sees it. See [events module](../../concepts/events-module.md#managing-an-event).
