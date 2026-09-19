---
type: Data Model
title: round_availability
description: One player's answer to whether they can play one round of an event; no row is no answer, and clearing an answer deletes the row.
resource: ../../../../app/models/round_availability.py
tags: [events, data]
generated: { by: claude-code/claude-fable-5-1, at: 2026-09-19T18:00:00Z }
verified: { by: process:test_okf, at: 2026-09-14T17:40:50Z }
sources:
  - id: model
    resource: ../../../../app/models/round_availability.py
    title: DBRoundAvailability
  - id: availability
    resource: ../../../../app/services/availability.py
    title: The player, the captain and the Discord card write the same row
---

# Schema

| Column | Type | Null | Meaning |
|---|---|---|---|
| `user_id` | INTEGER | no | The player the answer is about. Part of the key. |
| `season_id` | INTEGER | no | The event. Part of the key. |
| `playday` | INTEGER | no | The round number, 1 to the round count. Part of the key. |
| `round_id` | INTEGER | yes | The round row the answer is about. Null on a row older than the column. |
| `available` | BOOLEAN | no | True can play, false cannot. |
| `set_by_user_id` | INTEGER | no | Who wrote the answer: the player, or their captain. |
| `answered_at` | TIMESTAMP | yes | When the answer was written. Null on a row older than the column. |

# Keys and joins

Primary key (`user_id`, `season_id`, `playday`). Foreign keys: `user_id` and `set_by_user_id` to [users](users.md); `season_id` to [event](event.md); `round_id` to [event_round](event_round.md), cascade.

# Rules

The last write wins. A player's own write is refused before the round's check-in opens and after the round ends; a captain's is not, and `early_checkin` on the event opens every round that has not ended to the player. Dropping a round deletes its answers. Soft blocks never write here: a player whose blocks cover a whole round reads as blocked out on the payload, derived on the read. See [scheduling and availability](../../concepts/scheduling-and-availability.md).
