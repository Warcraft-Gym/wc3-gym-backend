---
type: Data Model
title: users
description: One player, matched by battle tag and Discord id, with the profile fields the forms write and three sync stamps.
resource: ../../../../app/models/user.py
tags: [auth, data]
generated: { by: claude-code/claude-fable-5-1, at: 2026-09-14T15:15:00Z }
verified: { by: process:test_okf, at: 2026-09-14T17:40:50Z }
sources:
  - id: model
    resource: ../../../../app/models/user.py
    title: User
  - id: users
    resource: ../../../../app/services/users.py
    title: UserService writes the profile, the ban and the W3C stamp
  - id: signup
    resource: ../../../../app/api/routes/public.py
    title: The public signup form creates or updates the row
---

# Schema

| Column | Type | Null | Meaning |
|---|---|---|---|
| `id` | INTEGER | no | Primary key. |
| `name` | VARCHAR | no | Display name. The career import matches `player_career_stats.player_name` on it. |
| `battleTag` | VARCHAR | no | Battle.net tag. Unique, case-insensitive, after trimming. The workbook import and the W3Champions client key on it. |
| `discordTag` | VARCHAR | no | Discord username. Unique among non-blank values. Blank means unknown. |
| `discordId` | VARCHAR | no | Discord account id. Unique among non-blank values. A Clerk session finds its player through it. Blank means unknown. |
| `mmr` | INTEGER | yes | The MMR typed on the signup or profile form. The W3Champions sync writes `w3cstats`, not this column. |
| `country` | VARCHAR | yes | ISO 3166-1 alpha-2 code, or a UK nation as `GB-SCT`. Drives the flag on cards. |
| `timezone` | VARCHAR | yes | IANA zone name. Soft blocks resolve their local times against it. Validated by `KnownTimeZone`. |
| `twitch_url` | VARCHAR | yes | The player's Twitch channel link. A video link is refused. |
| `youtube_url` | VARCHAR | yes | The player's YouTube channel link. A video link is refused. |
| `avatar_url` | VARCHAR | yes | The Discord avatar the login last read. Written by the login, never by a form. |
| `race` | VARCHAR | no | Main race: `RANDOM`, `HU`, `OC`, `NE`, `UD`. A form default only; the signup race on the season row decides scoring. |
| `w3c_synced_at` | TIMESTAMP | yes | When the W3Champions stats sync last read this player. Null means never. |
| `ladder_synced_at` | TIMESTAMP | yes | When the ladder match sync last read this player. Null means never. |
| `banned_at` | TIMESTAMP | yes | When an admin banned the player. Null means not banned. An entrant row warns on it and never refuses. |

# Keys and joins

Primary key `id`. Three unique expression indexes: `lower(trim("battleTag"))`, `lower(trim("discordTag"))` where not blank, `trim("discordId")` where not blank.

Pointed at by [user_team_season](user_team_season.md), [user_season_signup](user_season_signup.md), [team_season_captain](team_season_captain.md), [event_entrant](event_entrant.md), [event_award](event_award.md), [series](series.md), [draft_series](draft_series.md), [series_replay](series_replay.md), [series_veto_step](series_veto_step.md), [series_cast](series_cast.md), [round_availability](round_availability.md), [match_draft_mark](match_draft_mark.md), [user_block](user_block.md), [user_busy](user_busy.md), [fantasy_teams](fantasy_teams.md), [fantasy_team_player](fantasy_team_player.md), [fantasy_bets](fantasy_bets.md), [w3cstats](w3cstats.md), [w3c_ladder_matches](w3c_ladder_matches.md), [ladder_sync](ladder_sync.md), [player_career_stats](player_career_stats.md).

# Rules

- `race` is cosmetic. The race a player is scored on is `user_season_signup.race`. See [vocabulary](../../concepts/vocabulary.md).
- Two sync pipelines, two stamps: `w3c_synced_at` belongs to the stats sync, `ladder_synced_at` to the match sync. See [ladder and achievements](../../concepts/ladder-and-achievements.md).
- Never batch-alter this table on SQLite: it drops the expression index on the Discord tag. See [migrations](../migrations.md).
