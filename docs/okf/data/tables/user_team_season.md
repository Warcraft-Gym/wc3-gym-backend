---
type: Data Model
title: user_team_season
description: "One roster row: a player on one team in one season, written by the draft."
resource: ../../../../app/models/user_team_season.py
tags: [teams, data]
generated: { by: claude-code/claude-fable-5-1, at: 2026-09-14T15:15:00Z }
verified: { by: process:test_okf, at: 2026-09-14T16:47:40Z }
sources:
  - id: model
    resource: ../../../../app/models/user_team_season.py
    title: DBUserTeamSeason
  - id: teams
    resource: ../../../../app/services/teams.py
    title: add_players and remove_players
---

# Schema

| Column | Type | Null | Meaning |
|---|---|---|---|
| `user_id` | INTEGER | no | The player. Part of the key. |
| `team_id` | INTEGER | no | The team. Part of the key. |
| `season_id` | INTEGER | no | The season. Part of the key. |

# Keys and joins

Primary key (`user_id`, `team_id`, `season_id`). Foreign keys: `user_id` to [users](users.md); `team_id` to [teams](teams.md); `season_id` to [event](event.md).

# Rules

A drafted GNL player is a roster row, not an [event_entrant](event_entrant.md). The race the player is scored on is on [user_season_signup](user_season_signup.md). The `team` Discord role reads these rows. See [GNL season](../../concepts/gnl-season.md).
