---
type: Data Model
title: team_season
description: One team fielded in one GNL season; the row exists before the team has a captain or a roster.
resource: ../../../../app/models/team_season.py
tags: [schema, teams]
generated: { by: claude-code/claude-fable-5-1, at: 2026-09-14T15:15:00Z }
sources:
  - id: model
    resource: ../../../../app/models/team_season.py
    title: DBTeamSeason
  - id: seasons
    resource: ../../../../app/services/seasons.py
    title: add_teams and remove_teams
---

# Schema

| Column | Type | Null | Meaning |
|---|---|---|---|
| `team_id` | INTEGER | no | The team. Part of the key. |
| `season_id` | INTEGER | no | The season. Part of the key. |

# Keys and joins

Primary key (`team_id`, `season_id`). Foreign keys: `team_id` to [teams](teams.md); `season_id` to [event](event.md).

# Rules

The captains of the team in that season are [team_season_captain](team_season_captain.md) rows; the roster is [user_team_season](user_team_season.md). A team's Discord role is a [discord_role_binding](discord_role_binding.md), not a column here.
