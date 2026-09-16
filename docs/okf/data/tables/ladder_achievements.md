---
type: Data Model
title: ladder_achievements
description: One price for one achievement rule in one season, or for a player's lifetime when the season is null; the rule itself is code.
resource: ../../../../app/models/ladder_achievement.py
tags: [w3champions, data]
generated: { by: claude-code/claude-fable-5-1, at: 2026-09-14T15:15:00Z }
verified: { by: process:test_okf, at: 2026-09-14T17:40:50Z }
sources:
  - id: model
    resource: ../../../../app/models/ladder_achievement.py
    title: LadderAchievement
  - id: seasons
    resource: ../../../../app/services/seasons.py
    title: add seeds the default set; set_achievements replaces a season's rows
  - id: rules
    resource: ../../../../app/core/achievements.py
    title: The rule catalogue the rule_id names
---

# Schema

| Column | Type | Null | Meaning |
|---|---|---|---|
| `id` | INTEGER | no | Primary key. |
| `season_id` | INTEGER | yes | The season that pays the rule. Null means lifetime, scored over the player's whole history. |
| `rule_id` | VARCHAR | no | The id of a rule in `app/core/achievements.py`. A row naming no known rule pays nothing. |
| `points` | INTEGER | no | What the rule pays in that season. |
| `params` | JSON | no | The rule's numbers this row overrides, as a name-to-integer map. `{}` keeps the rule's defaults. |

# Keys and joins

Primary key `id`. Foreign key `season_id` to [event](event.md), cascade. Unique index on (`season_id`, `rule_id`), and a second unique index on `rule_id` where `season_id` is null, because the databases count nulls as distinct.

# Rules

A season drops a rule by having no row. Two seasons run the same rule as two rows. Badges derive from [w3c_ladder_matches](w3c_ladder_matches.md) on every read. See [ladder and achievements](../../concepts/ladder-and-achievements.md).
