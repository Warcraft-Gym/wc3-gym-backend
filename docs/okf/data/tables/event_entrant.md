---
type: Data Model
title: event_entrant
description: One player or one pre-made team in one event, with its race, seed, division, check-in and withdrawal stamps; a withdrawn entrant keeps its row.
resource: ../../../../app/models/event_entrant.py
tags: [events, data]
generated: { by: claude-code/claude-fable-5-1, at: 2026-09-15T09:00:00Z }
verified: { by: process:test_okf, at: 2026-09-14T17:40:50Z }
sources:
  - id: model
    resource: ../../../../app/models/event_entrant.py
    title: EventEntrant
  - id: events
    resource: ../../../../app/services/events.py
    title: The entrant, seed and division writes
  - id: engine
    resource: ../../../../app/services/stage_engine.py
    title: generate writes group_no, advance writes the seed
---

# Schema

| Column | Type | Null | Meaning |
|---|---|---|---|
| `id` | INTEGER | no | Primary key. |
| `event_id` | INTEGER | no | The event entered. |
| `user_id` | INTEGER | yes | The player, on a solo event. Exactly one of `user_id` and `team_id` is set. |
| `team_id` | INTEGER | yes | The pre-made team, on a team event. |
| `race` | VARCHAR | yes | The race a player enters on: `RANDOM`, `HU`, `OC`, `NE`, `UD`. A team row has none. The service refuses a player row without one. |
| `note` | VARCHAR | yes | What the entrant wants to work on, asked by a signup-only event. |
| `seed` | INTEGER | yes | The seed inside the division, from 1. Null until seeded, and cleared when a seed order leaves the entrant out. |
| `mmr_at_seed` | INTEGER | yes | The MMR the seed was cut from. |
| `seed_source` | VARCHAR | yes | What ordered the seeds: `mmr`, `random`, `manual`, `previous_stage`, `qualifier` or `invitation`. |
| `manual_placement` | BOOLEAN | no | On: an admin placed the entrant in its division by hand, so a reassign leaves it alone. |
| `division_id` | INTEGER | yes | The division the entrant plays in. Null while the event has one table. |
| `group_no` | INTEGER | yes | The group of a group stage. Written by generate. |
| `qualified_from_event_id` | INTEGER | yes | The qualifier the entrant came through. Null for a direct signup. Answered on the payload; no route writes it. |
| `channel` | VARCHAR | no | Where the signup came from: `web`, `bot` or `twitch`. |
| `checked_in_at` | TIMESTAMP | yes | When the entrant checked in. Null while not checked in. |
| `withdrawn_at` | TIMESTAMP | yes | When the entrant withdrew. Null means live. A return signup clears it and reuses the row. |
| `created_at` | TIMESTAMP | no | When the row was written. Set by the app. No route reads it. |

# Keys and joins

Primary key `id`. Foreign keys: `event_id` to [event](event.md), cascade; `user_id` to [users](users.md), cascade; `team_id` to [teams](teams.md), cascade; `division_id` to [event_division](event_division.md), set null; `qualified_from_event_id` to [event](event.md), set null. Unique constraints on (`event_id`, `user_id`, `race`) and (`event_id`, `team_id`); an event with `multi_entry` off keeps one row per player through the entrant write. Check constraint `one_entrant`: exactly one of `user_id` and `team_id` is set.

Pointed at by [series](series.md) (`entrant1_id`, `entrant2_id`), [series_side](series_side.md) and [event_award](event_award.md) through `entrant_id`.

# Rules

- The MMR and the warnings on the payload derive from [w3cstats](w3cstats.md) on every read. Eligibility warns and never refuses; only `entrant_cap` refuses. See [events module](../../concepts/events-module.md).
- A drafted GNL team is a [user_team_season](user_team_season.md) row, not an entrant.
