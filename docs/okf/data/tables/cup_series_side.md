---
type: Data Model
title: cup_series_side
description: One seat of a cup's free for all lobby, with the entrant in it and the place it finished.
resource: ../../../../app/models/cup_series.py
tags: [events, series, data]
generated: { by: claude-code/claude-opus-5-5, at: 2026-10-16T13:32:29Z }
sources:
  - id: model
    resource: ../../../../app/models/cup_series.py
    title: CupSeriesSide
  - id: engine
    resource: ../../../../app/services/cup_engine.py
    title: the lobby seats, set_places, set_sides, move_seat and _through
---

# Schema

| Column | Type | Null | Meaning |
|---|---|---|---|
| `series_id` | INTEGER | no | The cup series. Part of the key. |
| `side_no` | INTEGER | no | The seat; a lobby seats one entrant per side. Part of the key. |
| `user_id` | INTEGER | no | The player in the seat. 0 means the seat names no player: an empty seat or a team. Part of the key; no foreign key. |
| `entrant_id` | INTEGER | yes | The entrant in the seat. Null while the round before has not sent it. |
| `place` | INTEGER | yes | Where the seat finished, from 1. Null before the result. |

# Keys and joins

Primary key (`series_id`, `side_no`, `user_id`). Foreign keys: `series_id` to [cup_series](cup_series.md), cascade; `entrant_id` to [event_entrant](event_entrant.md), set null. Indexed on `user_id`.

# Rules

A two-sided cup series writes no row here. A runner seats a lobby again before it is played and enters its places, which settle it; a round whose every lobby has places seats the lobbies of the next round.

- An entrant sits in one lobby of a round. `PUT /cup-series/{id}/sides` refuses an entrant seated in another lobby of the round or withdrawn, and `POST /cup-series/{id}/move` moves one entrant between two unplayed lobbies of the round in one write.
- A seat whose entrant withdrew stays, and the lobby read marks it `left`, read from `event_entrant.withdrawn_at`. It takes no place, and the round after takes the next place instead; a seat that held a place before the withdrawal keeps it and goes on to no round.
- The replace write moves every seat of the old entrant to the new one, entrant and player, and refuses while one of those lobbies holds places. See [events module](../../concepts/events-module.md#cup-series).
