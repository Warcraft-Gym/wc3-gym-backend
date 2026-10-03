---
type: Data Model
title: koth_crown_event
description: One crown change of a KOTH bracket that no result shows, a hand pass, a step down or a throne a rule emptied, placed after the series it followed in the order of play.
resource: ../../../../app/models/koth_crown_event.py
tags: [events, koth, data]
generated: { by: claude-code/claude-opus-5-5, at: 2026-10-03T17:06:39Z }
sources:
  - id: model
    resource: ../../../../app/models/koth_crown_event.py
    title: KothCrownEvent
  - id: migration
    resource: ../../../../migrations/versions/55ae9f9d1db6_add_the_koth_crown_event_table.py
    title: The table
  - id: live
    resource: ../../../../app/services/koth/live.py
    title: The writes that pass, empty and fix the crown
  - id: board
    resource: ../../../../app/services/koth/board.py
    title: The walk of a bracket's results and crown events
---

# Schema

| Column | Type | Null | Meaning |
|---|---|---|---|
| `id` | INTEGER | no | Primary key. Rows with the same `after_sequence` apply in id order. |
| `division_id` | INTEGER | no | The KOTH bracket whose crown changed. |
| `after_sequence` | INTEGER | no | The highest `series.sequence` of a scored series of that bracket when the crown changed, 0 before any result. The change applies after that series and before every later one. |
| `entrant_id` | INTEGER | yes | The row the crown passed to. Null is an empty throne. |
| `created_at` | TIMESTAMP | no | When the change was written, UTC. |

# Keys and joins

Primary key `id`. Foreign key `division_id` to [event_division](event_division.md), cascade on delete, with an index. Foreign key `entrant_id` to [event_entrant](event_entrant.md), set null on delete.

# Rules

- A row is written when the crown changes player without a result: an admin passes the crown to another player or empties the throne, or a rule empties it (a king who leaves with nobody to forfeit to, a king moved to another bracket by hand or by a bounds save, a crowned row erased, a fix whose results crown a player who left). A pass between two race rows of one player writes no row, because the walk follows the player.
- The results of a bracket walked in sequence order, with these rows applied at their place, crown its king. A fix crowns by that walk, and the played rows of the board take their crown labels from it.
- A new series of the bracket takes a sequence above every `after_sequence` there, so it plays after every crown change already written.
- Clearing a night's results deletes the rows of its brackets. A night with no rows crowns by its results alone.
