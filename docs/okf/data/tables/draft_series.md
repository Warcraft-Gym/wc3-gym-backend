---
type: Data Model
title: draft_series
description: One series a captain proposed inside a GNL fixture, held apart from the series table until an admin promotes it.
resource: ../../../../app/models/draft_series.py
tags: [events, data]
generated: { by: claude-code/claude-fable-5-1, at: 2026-09-19T17:00:00Z }
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
| `replaces_series_id` | INTEGER | yes | The published series this pairing replaces; null on a plain pairing. |
| `created_at` | TIMESTAMP | yes | A creation stamp, answered on the payload. |
| `updated_at` | TIMESTAMP | yes | When the pairing last changed. |
| `created_by_user_id` | INTEGER | yes | Who wrote the pairing. Null when an admin token wrote it. |
| `updated_by_user_id` | INTEGER | yes | Who last changed it. Null when an admin token wrote it. |

# Keys and joins

Primary key `id`. Foreign keys: `match_id` to [matches](matches.md); `player1_id`, `player2_id`, `created_by_user_id` and `updated_by_user_id` to [users](users.md); `replaces_series_id` to [series](series.md), cascade. The payload answers the two names beside the two ids, read over the same statement.

# Rules

Promotion writes the [series](series.md) row and deletes the draft in one transaction. Deleting a fixture's drafts is one delete by `match_id`.

A fixture drafts up to the event's `series_per_round` pairings: published series plus open drafts, counted on create. A series a template wrote carries a `sequence` and counts by its template instead.

A pairing that names `replaces_series_id` replaces that published series: the series belongs to the same fixture, holds no result, and keeps one of its two players, and at most one draft replaces it. It is free of the round count. Publishing it removes the replaced series in the same transaction, with the booked time, the veto steps and the fantasy rows that hang on it; a series that holds a result or a replay is refused and nothing changes. See [GNL season](../../concepts/gnl-season.md).
