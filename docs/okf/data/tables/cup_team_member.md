---
type: Data Model
title: cup_team_member
description: One confirmed player of a cup team, the captain marked among them.
resource: ../../../../app/models/cup_team.py
tags: [events, teams, data]
generated: { by: claude-code/claude-opus-5-5, at: 2026-10-12T21:00:00Z }
sources:
  - id: model
    resource: ../../../../app/models/cup_team.py
    title: CupTeamMember
  - id: service
    resource: ../../../../app/services/cup_teams.py
    title: accept, leave, replace_member
---

# Schema

| Column | Type | Null | Meaning |
|---|---|---|---|
| `team_id` | INTEGER | no | Part of the primary key. The cup team. |
| `user_id` | INTEGER | no | Part of the primary key. The player. |
| `captain` | BOOLEAN | no | Whether the player captains the team. Defaults to false. |

# Keys and joins

Primary key (`team_id`, `user_id`). Foreign keys: `team_id` to [cup_team](cup_team.md) and `user_id` to [users](users.md), each `ON DELETE CASCADE`. Indexed on `user_id`.

# Rules

- The captain is a member with `captain` set; one team holds one captain.
- A member who is not the captain leaves before the team has played; the captain withdraws the team instead.
- A runner swaps a member for another player before the team has played; the new player takes the captaincy when the old one held it.
- The members are the team's roster: the entrant payload lists them, the team's rating is their mean, and each of them acts for the team's side of a cup series.
