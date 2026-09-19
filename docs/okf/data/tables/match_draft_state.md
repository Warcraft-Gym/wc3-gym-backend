---
type: Data Model
title: match_draft_state
description: The working largest MMR difference the captains pair inside while they draft one fixture, which stands in front of the stage setting.
resource: ../../../../app/models/match_draft.py
tags: [events, data]
generated: { by: claude-code/claude-fable-5-1, at: 2026-09-19T17:00:00Z }
sources:
  - id: model
    resource: ../../../../app/models/match_draft.py
    title: DBMatchDraftState
  - id: service
    resource: ../../../../app/services/draft_series.py
    title: DraftSeriesService reads the stage setting behind it
---

# Schema

| Column | Type | Null | Meaning |
|---|---|---|---|
| `match_id` | INTEGER | no | The fixture. Primary key. |
| `max_mmr_difference` | INTEGER | yes | The working value, 1 or more; null reads the stage setting. |

# Keys and joins

Primary key `match_id`, a foreign key to [matches](matches.md), cascade.

# Rules

A captain of either team of the fixture, or an admin, sets the value and clears it. Clearing puts the fixture back on the stage setting: `max_mmr_difference` of the captain-draft stage in [event_stage](event_stage.md), which reads 100 when the stage names none. The value guides the pairing screen; no write is refused for sitting outside it. See [GNL season](../../concepts/gnl-season.md).
