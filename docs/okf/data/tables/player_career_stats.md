---
type: Data Model
title: player_career_stats
description: One player's baseline from the seasons played before the app, imported from a CSV and never edited; the career totals add the app's seasons on every read.
resource: ../../../../app/models/player_career_stats.py
tags: [schema, w3champions]
generated: { by: claude-code/claude-fable-5-1, at: 2026-09-14T15:15:00Z }
sources:
  - id: model
    resource: ../../../../app/models/player_career_stats.py
    title: PlayerCareerStats
  - id: service
    resource: ../../../../app/services/player_career_stats.py
    title: The CSV import matches the player by name
  - id: career
    resource: ../../../../app/core/career.py
    title: The career rating rule folds the baseline in
---

# Schema

| Column | Type | Null | Meaning |
|---|---|---|---|
| `id` | INTEGER | no | Primary key. |
| `user_id` | INTEGER | yes | The player, matched by `users.name` at import. Null when no player matched. |
| `player_name` | VARCHAR | no | The name in the CSV. Unique. |
| `historical_rating` | INTEGER | yes | The rating carried from before the app. |
| `historical_series_won` | INTEGER | yes | Series won before the app. |
| `historical_series_lost` | INTEGER | yes | Series lost before the app. |
| `historical_games_won` | INTEGER | yes | Games won before the app. |
| `historical_games_lost` | INTEGER | yes | Games lost before the app. |
| `historical_seasons_played` | INTEGER | yes | Seasons played before the app. |

# Keys and joins

Primary key `id`. Foreign key `user_id` to [users](users.md), set null on delete. Unique constraint on `player_name`.

# Rules

No column stores a total or a current rating; `app/services/derived.py` folds these baselines with the app's seasons on every read. See [derived scores](../../concepts/derived-scores.md) and [the decision](../../decisions/derived-not-stored.md).
