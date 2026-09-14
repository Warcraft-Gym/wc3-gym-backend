---
type: Data Model
title: user_season_signup
description: One GNL signup: a player registered for one season on one race, with the draft order and fantasy tier an admin sets.
resource: ../../../../app/models/relationships.py
tags: [schema, teams]
generated: { by: claude-code/claude-fable-5-1, at: 2026-09-14T15:15:00Z }
sources:
  - id: model
    resource: ../../../../app/models/relationships.py
    title: DBUserSeasonSignup
  - id: seasons
    resource: ../../../../app/services/seasons.py
    title: add_user_signup, update_signup, get_signed_up_users
  - id: users
    resource: ../../../../app/services/users.py
    title: set_fantasy_tiers writes the tier
---

# Schema

| Column | Type | Null | Meaning |
|---|---|---|---|
| `user_id` | INTEGER | no | The player. Part of the key. |
| `season_id` | INTEGER | no | The season. Part of the key. |
| `race` | VARCHAR | no | The signup race: `RANDOM`, `HU`, `OC`, `NE`, `UD`. The race the league scores the player on. |
| `fantasy_tier` | INTEGER | yes | The tier an admin's allocation cut the player into. Null means not allocated; the read then derives the tier from the MMR on the apply date. |
| `draft_position` | INTEGER | yes | The slot an admin moved the player to in the draft order. Null sorts by MMR. |
| `draft_excluded` | BOOLEAN | no | On: an admin took the player out of the pick list, so they hold no draft slot. |

# Keys and joins

Primary key (`user_id`, `season_id`). Foreign keys: `user_id` to [users](users.md); `season_id` to [event](event.md).

# Rules

- `fantasy_tier_pinned` on the payload is derived: true when `fantasy_tier` is set and the season has `fantasy_tiers_applied_at`. Nothing stores it.
- A hand correction to the draft order is a position, never an adjusted MMR. See [the decision](../../decisions/draft-order-rerank.md) and [GNL season](../../concepts/gnl-season.md).
- The `gnl_participant` Discord role reads these rows.
