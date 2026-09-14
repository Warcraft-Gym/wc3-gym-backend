---
type: Data Model
title: fantasy_team_player
description: One player drafted onto one fantasy team.
resource: ../../../../app/models/relationships.py
tags: [schema, fantasy]
generated: { by: claude-code/claude-fable-5-1, at: 2026-09-14T15:15:00Z }
sources:
  - id: model
    resource: ../../../../app/models/relationships.py
    title: DBFantasyTeamPlayer
  - id: service
    resource: ../../../../app/services/fantasy_teams.py
    title: FantasyTeamService writes the drafted players
---

# Schema

| Column | Type | Null | Meaning |
|---|---|---|---|
| `fantasy_team_id` | INTEGER | no | The fantasy team. Part of the key. |
| `user_id` | INTEGER | no | The drafted player. Part of the key. |

# Keys and joins

Primary key (`fantasy_team_id`, `user_id`). Foreign keys: `fantasy_team_id` to [fantasy_teams](fantasy_teams.md); `user_id` to [users](users.md).

# Rules

A drafted player pays the points of every series they played that season, plus bench points for a round with no series, computed on every read. See [fantasy](../../concepts/fantasy.md).
