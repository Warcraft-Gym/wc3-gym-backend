---
type: Data Model
title: cup_entrant_pin
description: A cup player's two pins, its division placed by hand and its seed a reshuffle keeps, held apart from the flag KOTH reads.
resource: ../../../../app/models/cup_settings.py
tags: [events, data]
generated: { by: claude-code/claude-opus-5-5, at: 2026-10-13T10:30:00Z }
sources:
  - id: model
    resource: ../../../../app/models/cup_settings.py
    title: CupEntrantPin
  - id: rules
    resource: ../../../../app/services/cup_divisions.py
    title: A cup's division rules
---

# Schema

| Column | Type | Null | Meaning |
|---|---|---|---|
| `entrant_id` | INTEGER | no | Primary key. The cup's entrant. |
| `division_pinned` | BOOLEAN | no | On: a runner placed the player in its division by hand, so a new cut leaves it there. Defaults to false. |
| `seed_pinned` | BOOLEAN | no | On: a reshuffle keeps the player's seed. Defaults to false. |

# Keys and joins

Primary key `entrant_id`, a foreign key to [event_entrant](event_entrant.md), `ON DELETE CASCADE`.

# Rules

- A cup's division move (`PUT /events/{id}/entrants/{entrant_id}`) writes `division_pinned`; `PUT /events/{id}/entrants/{entrant_id}/pins` sets either pin, and refuses any event that is no cup.
- A new division list takes the division pins back and keeps the seed pins; a seed write keeps the seed pins and leaves the division pins.
- The entrant read answers both as `division_pinned` and `seed_pinned` on a cup, and null on any other kind. `event_entrant.manual_placement` keeps its meaning for KOTH and sign-up lists.
