---
type: Data Model
title: cup_team_invite
description: One player invited into a cup team who has not answered yet; accepting makes them a member, declining deletes the row.
resource: ../../../../app/models/cup_team.py
tags: [events, teams, data]
generated: { by: claude-code/claude-opus-5-5, at: 2026-10-12T21:00:00Z }
sources:
  - id: model
    resource: ../../../../app/models/cup_team.py
    title: CupTeamInvite
  - id: service
    resource: ../../../../app/services/cup_teams.py
    title: sign_up, invite, accept, decline, take_back
---

# Schema

| Column | Type | Null | Meaning |
|---|---|---|---|
| `team_id` | INTEGER | no | Part of the primary key. The cup team that invites. |
| `user_id` | INTEGER | no | Part of the primary key. The invited player. |
| `event_id` | INTEGER | no | The cup the team plays, so one read finds every invite of a cup. |
| `invited_at` | TIMESTAMP | no | When the captain invited the player. Set by the app. |

# Keys and joins

Primary key (`team_id`, `user_id`). Foreign keys: `team_id` to [cup_team](cup_team.md), `user_id` to [users](users.md) and `event_id` to [event](event.md), each `ON DELETE CASCADE`. Indexed on `user_id` and `event_id`.

# Rules

- A cup team's members ([cup_team_member](cup_team_member.md)) are confirmed players only; an invited player stands here until they answer.
- `POST /events/{id}/cup-teams` writes one row per player the captain names; `POST /events/{id}/cup-teams/{team_id}/invites` adds one into a free place, and `DELETE …/invites/{user_id}` takes it back. Both are the captain's.
- `POST …/accept` holds the player to the cup's eligibility again, writes the member row and deletes this one; `POST …/decline` deletes it.
- A player stands in one team of a cup at most, as a member or here.
- `GET /me/team-invites` answers the caller's rows with the team, its captain and the cup. A withdrawn team deletes its rows, and a removed team takes them along.
