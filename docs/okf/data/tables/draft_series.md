---
type: Data Model
title: draft_series
description: One series a captain proposed inside a GNL fixture, held apart from the series table until an admin promotes it.
resource: ../../../../app/models/draft_series.py
tags: [events, data]
generated: { by: claude-code/claude-fable-5-1, at: 2026-09-14T15:15:00Z }
verified: { by: process:test_okf, at: 2026-09-14T17:40:50Z }
sources:
  - id: model
    resource: ../../../../app/models/draft_series.py
    title: DraftSeries
  - id: service
    resource: ../../../../app/services/draft_series.py
    title: DraftSeriesService; convert_to_series builds the promoted row
---

# Schema

| Column | Type | Null | Meaning |
|---|---|---|---|
| `id` | INTEGER | no | Primary key. |
| `match_id` | INTEGER | no | The fixture the proposal belongs to. |
| `date_time` | TIMESTAMP | yes | A proposed time, UTC. |
| `player1_id` | INTEGER | no | Side A's player. |
| `player2_id` | INTEGER | no | Side B's player. |
| `player1_score` | INTEGER | yes | Maps side A won, 0 to 2. Usually null on a draft. |
| `player2_score` | INTEGER | yes | Maps side B won, 0 to 2. |
| `host_player_id` | INTEGER | no | The player who hosts. No foreign key. |
| `is_fantasy_match` | BOOLEAN | yes | Carried onto the promoted series. Defaults to false. |
| `created_at` | TIMESTAMP | yes | A creation stamp, answered on the payload. |

# Keys and joins

Primary key `id`. Foreign keys: `match_id` to [matches](matches.md); `player1_id` and `player2_id` to [users](users.md).

# Rules

Promotion copies the row into a `SeriesCreate` and the series service writes the [series](series.md) row. Deleting a fixture's drafts is one delete by `match_id`. See [GNL season](../../concepts/gnl-season.md).
