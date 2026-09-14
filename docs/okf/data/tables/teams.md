---
type: Data Model
title: teams
description: "One team: its short name, long name and the public URL of its logo."
resource: ../../../../app/models/team.py
tags: [teams, data]
generated: { by: claude-code/claude-fable-5-1, at: 2026-09-14T15:15:00Z }
verified: { by: process:test_okf, at: 2026-09-14T17:40:50Z }
sources:
  - id: model
    resource: ../../../../app/models/team.py
    title: Team
  - id: teams
    resource: ../../../../app/services/teams.py
    title: TeamService
  - id: blob
    resource: ../../../../app/services/blob.py
    title: The logo upload writes icon_url
---

# Schema

| Column | Type | Null | Meaning |
|---|---|---|---|
| `id` | INTEGER | no | Primary key. |
| `name` | VARCHAR | no | The short name. The workbook import matches a team on it. |
| `long_name` | VARCHAR | yes | The full name. |
| `icon_url` | VARCHAR | yes | The public URL of the logo in the blob store. Null means the default logo. Written by `POST /teams/{id}/image`. |

# Keys and joins

Primary key `id`. No foreign keys. Pointed at by [team_season](team_season.md), [team_season_captain](team_season_captain.md), [user_team_season](user_team_season.md), [event_entrant](event_entrant.md), [event_award](event_award.md), [matches](matches.md) (`team1_id`, `team2_id`), [fantasy_teams](fantasy_teams.md) (`drafted_team_id`, `grind_team_id`), [discord_role_binding](discord_role_binding.md).

# Rules

No bytes column; the store follows the row and a deleted team drops its picture after the commit. Standings derive from the fixtures on every read. See [pictures and replays](../../concepts/pictures-and-replays.md) and [the decision](../../decisions/pictures-as-urls.md).
