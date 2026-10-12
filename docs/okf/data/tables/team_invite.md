---
type: Data Model
title: team_invite
description: One player invited into a cup team who has not answered yet; accepting moves them into the roster, declining deletes the row.
resource: ../../../../app/models/team_invite.py
tags: [events, data]
generated: { by: claude-code/claude-opus-5-5, at: 2026-10-08T18:00:00Z }
sources:
  - id: model
    resource: ../../../../app/models/team_invite.py
    title: TeamInvite
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

Primary key (`team_id`, `user_id`). Foreign keys: `team_id` to [teams](teams.md), `user_id` to [users](users.md) and `event_id` to [event](event.md), each `ON DELETE CASCADE`. Indexed on `user_id` and `event_id`.

# Rules

- The roster of a cup team ([user_team_season](user_team_season.md) against the cup) holds confirmed players only; an invited player stands here until they answer.
- `POST /events/{id}/cup-teams` writes one row per player the captain names; `POST /events/{id}/cup-teams/{team_id}/invites` adds one into a free place, and `DELETE …/invites/{user_id}` takes it back. Both are the captain's.
- `POST …/accept` holds the player to the cup's eligibility again, writes the roster row and deletes this one; `POST …/decline` deletes it.
- A player stands in one team of a cup at most, on its roster or here.
- `GET /me/team-invites` answers the caller's rows with the team, its captain and the cup. A withdrawn team deletes its rows.
