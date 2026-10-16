---
type: Data Model
title: cup_leg_checkin
description: One player checked in for one round of a cup; the round's draw takes these players alone.
resource: ../../../../app/models/cup_rounds.py
tags: [events, data]
generated: { by: claude-code/claude-opus-5-5, at: 2026-10-16T18:00:00Z }
sources:
  - id: model
    resource: ../../../../app/models/cup_rounds.py
    title: CupLegCheckin
  - id: rules
    resource: ../../../../app/services/cup_rounds.py
    title: A cup's rounds
---

# Schema

| Column | Type | Null | Meaning |
|---|---|---|---|
| `leg_id` | INTEGER | no | Part of the primary key. The round. |
| `entrant_id` | INTEGER | no | Part of the primary key. The cup's entrant. |
| `checked_in_at` | TIMESTAMP | no | When the entrant checked in. |

# Keys and joins

Primary key (`leg_id`, `entrant_id`). Foreign key `leg_id` to [cup_leg](cup_leg.md) and `entrant_id` to [event_entrant](event_entrant.md), both `ON DELETE CASCADE`.

# Rules

- `POST /events/{id}/legs/{leg_id}/checkins` checks an entrant in and `DELETE` on the same path checks it out, while the round is not drawn. A player checks in their own entry, or their cup team's, from `checkin_opens_minutes` before the round's `starts_at` (any time with `early_checkin` on) until the earliest of `checkin_closes_minutes` before it, a runner's close of the round by hand (`cup_leg.checkin_closed_at`) and the cup's close or cancel; a runner names any `entrant_id` at any time before the draw. Outside the window a player reads `403 {"error": "checkin_closed"}`.
- `POST /events/{id}/legs/{leg_id}/checkins/everyone` is a runner's check-in of every playing entrant.
- A signup after the first round is drawn joins the cup for its later rounds and goes on no waitlist; the entrant cap still holds.
