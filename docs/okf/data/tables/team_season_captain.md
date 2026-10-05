---
type: Data Model
title: team_season_captain
description: "One captain seat: a player who captains one team in one season; the seat is what makes an account a captain."
resource: ../../../../app/models/relationships.py
tags: [teams, data]
generated: { by: claude-code/claude-opus-5-5, at: 2026-10-05T12:00:00Z }
verified: { by: process:test_okf, at: 2026-09-24T09:51:01Z }
sources:
  - id: model
    resource: ../../../../app/models/relationships.py
    title: DBTeamSeasonCaptain
  - id: teams
    resource: ../../../../app/services/teams.py
    title: set_captains replaces the seats; captain_seats answers them for a login
---

# Schema

| Column | Type | Null | Meaning |
|---|---|---|---|
| `team_id` | INTEGER | no | The team. Part of the key. |
| `season_id` | INTEGER | no | The season. Part of the key. |
| `user_id` | INTEGER | no | The captain. Part of the key. A team may hold any number of seats. |

# Keys and joins

Primary key (`team_id`, `season_id`, `user_id`). Foreign keys: `team_id` to [teams](teams.md); `season_id` to [event](event.md), cascade; `user_id` to [users](users.md).

# Rules

The captain role is read from these rows on every request, for a running season. A Fantasy Captain holds no seat. See [roles and permissions](../../concepts/roles-and-permissions.md).

A player's history, `GET /users/{user_id}/history` and `GET /player-history`, carries `captain_of`: every seat the player holds as `{season_id, team_id, team_name}`, newest season first, read in one statement. `GET /users/{user_id}/seasons` reads the same seats beside the roster seats: a season with a captain seat and no roster seat answers `captain_only`, and `is_captain` says the player captained the team the row names.
