---
type: Data Model
title: matches
description: "One fixture: two teams meeting in one round of an event, which the series between their players hang under."
resource: ../../../../app/models/match.py
tags: [events, data]
generated: { by: claude-code/claude-fable-5-1, at: 2026-09-14T15:15:00Z }
verified: { by: process:test_okf, at: 2026-09-14T16:47:40Z }
sources:
  - id: model
    resource: ../../../../app/models/match.py
    title: Match
  - id: matches
    resource: ../../../../app/services/matches.py
    title: MatchService writes the GNL fixtures
  - id: engine
    resource: ../../../../app/services/stage_engine.py
    title: A round robin over team entrants writes a fixture per pair
  - id: round-link
    resource: ../../../../app/services/round_link.py
    title: round_id is resolved on flush
---

# Schema

| Column | Type | Null | Meaning |
|---|---|---|---|
| `id` | INTEGER | no | Primary key. |
| `team1_id` | INTEGER | no | The first team. |
| `team2_id` | INTEGER | no | The second team. A-vs-B and B-vs-A are different rows. |
| `season_id` | INTEGER | no | The event the fixture belongs to. |
| `playday` | INTEGER | no | The round number. Kept beside `round_id` so the GNL payloads hold. |
| `fixed_map_id` | INTEGER | yes | A map fixed for this fixture. Null means the round's map applies. |
| `round_id` | INTEGER | yes | The round the fixture is played in. Resolved from (`season_id`, `playday`) on every flush. |
| `division_id` | INTEGER | yes | The division the fixture is played in. Null while the event has one table. |

# Keys and joins

Primary key `id`. Foreign keys: `team1_id` and `team2_id` to [teams](teams.md), cascade; `season_id` to [event](event.md), cascade; `fixed_map_id` to [maps](maps.md); `round_id` to [event_round](event_round.md), cascade; `division_id` to [event_division](event_division.md), set null. Unique index on (`season_id`, `team1_id`, `team2_id`, `playday`).

Pointed at by [series](series.md) and [draft_series](draft_series.md) through `match_id`.

# Rules

The fixture score is the sum of its series points, computed on every read. "Match" is the GNL admin word for a fixture; never use it for a series. See [derived scores](../../concepts/derived-scores.md) and [vocabulary](../../concepts/vocabulary.md).
