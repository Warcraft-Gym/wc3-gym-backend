---
type: Data Model
title: cup_team
description: A team made for one cup, signed up by its captain; it lives as long as its cup and no GNL read sees it.
resource: ../../../../app/models/cup_team.py
tags: [events, teams, data]
generated: { by: claude-code/claude-opus-5-5, at: 2026-10-12T21:00:00Z }
sources:
  - id: model
    resource: ../../../../app/models/cup_team.py
    title: CupTeam
  - id: service
    resource: ../../../../app/services/cup_teams.py
    title: the team writes of a team cup
---

# Schema

| Column | Type | Null | Meaning |
|---|---|---|---|
| `id` | INTEGER | no | Primary key. |
| `event_id` | INTEGER | no | The cup the team was made for. |
| `name` | VARCHAR(50) | no | The name the captain gave it. |
| `created_at` | TIMESTAMP | no | When the team was signed up. Set by the database. |

# Keys and joins

Primary key `id`. Foreign key `event_id` to [event](event.md), `ON DELETE CASCADE`, indexed. The team's entrant row is the [event_entrant](event_entrant.md) whose `cup_team_id` names it; its players are [cup_team_member](cup_team_member.md) rows and its open invitations [cup_team_invite](cup_team_invite.md) rows.

# Rules

- A cup team is no league team: it holds no [teams](teams.md) row, no captain seat and no roster of a GNL season, so the GNL captain claims, stats, trophies and Discord roles never read it.
- A team plays as one side. Every member acts for that side of a cup series: see [cup series](../../concepts/events-module.md#cup-series).
- Removing the team's entrant deletes the team, its members and its invitations, so every player of it is free again.
- See [cup teams live for one cup](../../decisions/cup-teams-live-for-one-cup.md).
