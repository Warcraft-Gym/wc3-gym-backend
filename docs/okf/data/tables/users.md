---
type: Data Model
title: users
description: One player, made by the first way in that meets them and found by battle tag or Discord id, with the profile fields the forms write and three sync stamps.
resource: ../../../../app/models/user.py
tags: [auth, data]
generated: { by: claude-code/claude-opus-5-5, at: 2026-09-24T07:07:32Z }
verified: { by: process:test_okf, at: 2026-09-24T07:07:47Z }
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

# How a row is made

A row is made by the first way in that meets the player, and each way in looks for an existing row by its own key. A login never makes a row: `GET /me` reads the row whose `discordId` is the session's Discord id, and answers `user` null when there is none.

| Way in | Looks for a row by | Makes a row with |
|---|---|---|
| The member signup, `POST /signup` | `discordId`, then `battleTag` without case, then `discordTag` exactly | the form's fields and the session's Discord id and tag |
| An `anyone` entrant, the Twitch chat signup, an admin who types a battle tag | `battleTag`, without case | the tag, its name part as `name`, blank Discord fields |
| The workbook import | `battleTag`, without case | the workbook row's fields |
| The fantasy import | `discordTag`, without case | a captain on no roster |

Because `battleTag`, `discordTag` and `discordId` are not nullable, a row that knows no value carries a blank or a stand-in: a Players row of the workbook must name a Discord id, a Fantasy Users row with none carries a blank, and a fantasy captain with no battle tag carries a tag that begins `Fantasy_User#`. See [events module](../../concepts/events-module.md) and [KOTH](../../concepts/koth.md) for the entrant ways in.

The member signup takes a row only when no other login holds it. A row has a login when its `discordId` is neither blank nor a `gnl-` stand-in. The login's own row comes first. A row whose `battleTag` the member types exactly and that has no login becomes the member's. A `battleTag` another login holds answers 409 with an `error` that names the tag. A row with no login that matches only on `discordTag` answers 409 with a `link` object of `player`, `discord_id` and `battle_tag`, the details an admin needs to set `discordId` on that row; so does a row with no login that holds the typed tag when the member already has a row. A `discordTag` that a row with another login holds is left blank on the member's row, because Discord names repeat and the column is unique.

# Rules

- `race` is cosmetic. The race a player is scored on is `user_season_signup.race`. See [vocabulary](../../concepts/vocabulary.md).
- Two sync pipelines, two stamps: `w3c_synced_at` belongs to the stats sync, `ladder_synced_at` to the match sync. See [ladder and achievements](../../concepts/ladder-and-achievements.md).
- Never batch-alter this table on SQLite: it drops the expression index on the Discord tag. See [migrations](../migrations.md).
