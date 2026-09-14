---
type: Data Model
title: fantasy_teams
description: One Fantasy Captain's team for one season: the real team, the race and the grind pick it drafted; every score derives.
resource: ../../../../app/models/fantasy_team.py
tags: [schema, fantasy]
generated: { by: claude-code/claude-fable-5-1, at: 2026-09-14T15:15:00Z }
sources:
  - id: model
    resource: ../../../../app/models/fantasy_team.py
    title: FantasyTeam
  - id: service
    resource: ../../../../app/services/fantasy_teams.py
    title: FantasyTeamService
  - id: import
    resource: ../../../../app/services/fantasy_import.py
    title: The fantasy workbook import
---

# Schema

| Column | Type | Null | Meaning |
|---|---|---|---|
| `id` | INTEGER | no | Primary key. |
| `name` | VARCHAR | no | The team name. Unique per season, case-insensitive. |
| `season_id` | INTEGER | no | The season the team plays in. |
| `captain_id` | INTEGER | no | The member who owns the team, the Fantasy Captain. One team per member per season. |
| `drafted_team_id` | INTEGER | yes | The real team drafted, paid by its standing. |
| `grind_team_id` | INTEGER | yes | The second team a bettor picks when the season offers `fantasy_grind`, paid by its rank on achievement points. |
| `drafted_race` | VARCHAR | yes | The race drafted, paid by the weekly race table: `RANDOM`, `HU`, `OC`, `NE`, `UD`. |

# Keys and joins

Primary key `id`. Foreign keys: `season_id` to [event](event.md), cascade; `captain_id` to [users](users.md), cascade; `drafted_team_id` to [teams](teams.md), cascade; `grind_team_id` to [teams](teams.md), set null. Unique indexes on (`season_id`, `lower(trim(name))`) and (`season_id`, `captain_id`). Pointed at by [fantasy_team_player](fantasy_team_player.md).

# Rules

No column stores a total. Creation locks when the season commences. The `fantasy` Discord role reads these rows. See [fantasy](../../concepts/fantasy.md) and [derived scores](../../concepts/derived-scores.md).
