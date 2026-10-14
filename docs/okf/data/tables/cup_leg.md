---
type: Data Model
title: cup_leg
description: One round of a cup played over several rounds, a competition of its own on its own date, with its own copy of the cup's stages.
resource: ../../../../app/models/cup_rounds.py
tags: [events, data]
generated: { by: claude-code/claude-opus-5-5, at: 2026-10-14T12:00:00Z }
sources:
  - id: model
    resource: ../../../../app/models/cup_rounds.py
    title: CupLeg
  - id: rules
    resource: ../../../../app/services/cup_rounds.py
    title: A cup's rounds
---

# Schema

| Column | Type | Null | Meaning |
|---|---|---|---|
| `id` | INTEGER | no | Primary key. |
| `event_id` | INTEGER | no | The cup. |
| `number` | INTEGER | no | The round's place in the cup, from 1, in the order the rounds are played. |
| `name` | VARCHAR(50) | yes | The round's name; `Round {number}` when the create names none. |
| `starts_at` | TIMESTAMP | yes | When the round starts. |
| `finished_at` | TIMESTAMP | yes | When a runner finished the round. Its places count in the overall table from then on. |

# Keys and joins

Foreign key `event_id` to [event](event.md), `ON DELETE CASCADE`, indexed. [cup_leg_stage](cup_leg_stage.md) names the stages a round plays, and [cup_leg_checkin](cup_leg_checkin.md) the players who play it.

# Rules

- `POST /events` for a cup with `legs` writes one row per entry, two or more, and copies the body's `stages` into every round. The cup's own check-in (`event.checkin_enabled`) is off; its players check in per round.
- While the cup is open a runner renames a round or moves its start (`PUT /events/{id}/legs/{leg_id}`), adds one after the last (`POST /events/{id}/legs`), and removes one not drawn (`DELETE /events/{id}/legs/{leg_id}`); the rounds keep their order and a cup keeps two or more, and the first round's start is the cup's.
- The full event read answers the rounds as `cup_legs`, each with its `stage_ids` in play order and the entrants `checked_in`; it reads null on a cup of one evening, on any other kind and on a list read.
- `POST /events/{id}/legs/{leg_id}/finish` finishes a round once every series of it holds a result, and clears every entrant's seed, so the next round seeds afresh. `DELETE` on the same path takes the finish back while the cup is open; until then the round's draw cannot be undone.
- The rounds are the cup's alone; no GNL or KOTH read sees them. `event_round` is a column of a bracket, not one of these. See [events module](../../concepts/events-module.md#cup-rounds).
