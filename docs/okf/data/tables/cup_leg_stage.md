---
type: Data Model
title: cup_leg_stage
description: Which round of a cup one of its stages is played in, so a round's draw, neighbours and places stay inside that round.
resource: ../../../../app/models/cup_rounds.py
tags: [events, data]
generated: { by: claude-code/claude-opus-5-5, at: 2026-10-25T21:00:00Z }
sources:
  - id: model
    resource: ../../../../app/models/cup_rounds.py
    title: CupLegStage
  - id: engine
    resource: ../../../../app/services/cup_engine.py
    title: The cup engine
---

# Schema

| Column | Type | Null | Meaning |
|---|---|---|---|
| `stage_id` | INTEGER | no | Primary key. The stage. |
| `leg_id` | INTEGER | no | The round it is played in. |

# Keys and joins

Primary key `stage_id`, a foreign key to [event_stage](event_stage.md), `ON DELETE CASCADE`. Foreign key `leg_id` to [cup_leg](cup_leg.md), `ON DELETE CASCADE`, indexed.

# Rules

- A stage of a round draws and seeds the entrants checked in for that round alone, a seed write included, and its previous and next stage are stages of the same round, so the first stage of a round seeds from no earlier stage and the last advances into none.
- The stage positions run on through the rounds, so the cup's stage list reads in play order.
- `PUT /events/{id}/stages` on a cup with rounds takes one round's stages and writes them onto every round, or every stage in place. Until the cup's first draw a body of one round's stages may change how many stages a round plays, and every round's rows are written again from it; after the draw that body is refused.
