---
type: Data Model
title: match_draft_mark
description: One team's advisory Ready mark on the draft of one fixture, plus the moment that team last read the pairings.
resource: ../../../../app/models/match_draft.py
tags: [events, data]
generated: { by: claude-code/claude-fable-5-1, at: 2026-09-19T17:00:00Z }
sources:
  - id: model
    resource: ../../../../app/models/match_draft.py
    title: DBMatchDraftMark
  - id: service
    resource: ../../../../app/services/draft_series.py
    title: DraftSeriesService writes the mark and clears it
---

# Schema

| Column | Type | Null | Meaning |
|---|---|---|---|
| `match_id` | INTEGER | no | The fixture the mark belongs to. Part of the key. |
| `team_id` | INTEGER | no | The team that holds the mark. Part of the key. |
| `ready_by_user_id` | INTEGER | yes | The captain who marked the team ready; null when no mark stands. |
| `ready_at` | TIMESTAMP | yes | When the mark was set. |
| `seen_at` | TIMESTAMP | yes | When the team last read the pairings. |

# Keys and joins

Primary key (`match_id`, `team_id`). Foreign keys: `match_id` to [matches](matches.md), cascade; `team_id` to [teams](teams.md), cascade; `ready_by_user_id` to [users](users.md), set null.

# Rules

The row is written on its first use. A captain sets and clears the mark of their own team, and an admin sets either. Creating, editing or deleting a pairing of the fixture clears both teams' marks in the same transaction. The mark is advisory: it never blocks publishing a pairing. `seen_at` is written by its own call, never as a side effect of a read, so a page that lists the pairings marks the ones changed after it. See [GNL season](../../concepts/gnl-season.md).
