---
type: Data Model
title: users
description: One person, made by the first way in that meets them and found by any battle tag they hold or by Discord id, with the profile fields the forms write and three sync stamps.
resource: ../../../../app/models/user.py
tags: [auth, data]
generated: { by: claude-code/claude-opus-5-5, at: 2026-09-24T10:00:35Z }
verified: { by: process:test_okf, at: 2026-09-24T09:51:01Z }
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
  - id: tags
    resource: ../../../../app/services/battle_tags.py
    title: Finds a person by any tag and attaches a tag
  - id: merge
    resource: ../../../../app/services/merge.py
    title: The merge of two people
---

# Schema

| Column | Type | Null | Meaning |
|---|---|---|---|
| `id` | INTEGER | no | Primary key. |
| `name` | VARCHAR | no | Display name. The career import matches `player_career_stats.player_name` on it. |
| `battleTag` | VARCHAR | yes | A copy of the tag of the person's active [user_battle_tag](user_battle_tag.md) row; `set_active_tag` writes both. Unique, case-insensitive, after trimming. The W3Champions stats sync reads it. An importer stand-in person holds its stand-in tag here and has no tag row. |
| `discordTag` | VARCHAR | yes | Discord username. Unique among non-blank values. Null or blank means unknown. A person who never logged in may keep an old sheet handle here as a hint. |
| `discordId` | VARCHAR | yes | Discord account id. Unique among non-blank values. A Clerk session finds its player through it. Null means the person never logged in; blank means unknown. |
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

Primary key `id`. Three unique expression indexes: `lower(trim("battleTag"))`, `lower(trim("discordTag"))` where not blank, `trim("discordId")` where not blank. A unique index skips null, so any number of rows hold a null tag or id.

Pointed at by [user_battle_tag](user_battle_tag.md), [user_team_season](user_team_season.md), [user_season_signup](user_season_signup.md), [team_season_captain](team_season_captain.md), [event_entrant](event_entrant.md), [event_award](event_award.md), [series](series.md), [draft_series](draft_series.md), [series_replay](series_replay.md), [series_veto_step](series_veto_step.md), [series_cast](series_cast.md), [round_availability](round_availability.md), [match_draft_mark](match_draft_mark.md), [user_block](user_block.md), [user_busy](user_busy.md), [fantasy_teams](fantasy_teams.md), [fantasy_team_player](fantasy_team_player.md), [fantasy_bets](fantasy_bets.md), [w3cstats](w3cstats.md), [w3c_ladder_matches](w3c_ladder_matches.md), [ladder_sync](ladder_sync.md), [player_career_stats](player_career_stats.md).

# How a row is made

A row is made by the first way in that meets the player, and each way in looks for an existing row by its own key. A login never makes a row: `GET /me` reads the row whose `discordId` is the session's Discord id, and answers `user` null when there is none.

| Way in | Looks for a row by | Makes a row with |
|---|---|---|
| The member signup, `POST /signup` | `discordId`, then any tag without case, then `discordTag`, without case | the form's fields and the session's Discord id and tag, and a tag row with source `signup` |
| An `anyone` entrant, the Twitch chat signup, an admin who types a battle tag | any tag, without case | the tag, its name part as `name`, blank Discord fields, and a tag row with source `signup` |
| The workbook import | any tag, without case; a stand-in tag by `battleTag` | the workbook row's fields, and a tag row with source `sheet` |
| The fantasy import | `discordTag`, without case | a captain on no roster |
| An admin, `POST /users` | none | the body's fields, and a tag row with source `admin` |

"Any tag" means a [user_battle_tag](user_battle_tag.md) row, so a person's second tag finds them at every door. A tag sent to `PUT /users/{id}`, `PUT /user-info` or a member signup that the person does not hold yet becomes a new tag row and the active one; the tag they held before stays theirs. A tag another person holds answers 409 with an `error` that names it.

The ways in write a blank or a stand-in where they know no value: a Players row of the workbook must name a Discord id, a Fantasy Users row with none carries a blank, a fantasy captain with no battle tag carries a tag that begins `Fantasy_User#`, and the review season's made-up players carry a tag that begins `Review#`. A person from an earlier season who never logged in has a null `discordId`: the workbook import writes null where the sheet holds a `gnl-` stand-in id, and null for the stand-in Discord tag that came with it. See [events module](../../concepts/events-module.md) and [KOTH](../../concepts/koth.md) for the entrant ways in.

The member signup takes a row only when no other login holds it. A row has a login when its `discordId` is neither null, blank, nor a `gnl-` stand-in. The login's own row comes first. A row that holds the tag the member types, without case, and that has no login becomes the member's; the tag becomes its active one. A `battleTag` another login holds answers 409 with an `error` that names the tag. A row with no login that matches only on `discordTag` answers 409 with a `link` object of `player`, `discord_id` and `battle_tag`, the details an admin needs to set `discordId` on that row; so does a row with no login that holds the typed tag when the member already has a row. A `discordTag` that a row with another login holds is left blank on the member's row, because Discord names repeat and the column is unique.

# Rules

- `race` is cosmetic. The race a player is scored on is `user_season_signup.race`. See [vocabulary](../../concepts/vocabulary.md).
- Two sync pipelines, two stamps: `w3c_synced_at` belongs to the stats sync, `ladder_synced_at` to the match sync. See [ladder and achievements](../../concepts/ladder-and-achievements.md).
- A person holds many battle tags in [user_battle_tag](user_battle_tag.md); `battleTag` is a copy of the active one. Every lookup by tag reads that table.
- `GET /users/{key}` takes an id, or any tag the person holds, without case.
- The user reads (`GET /users/{key}`, `GET /users`, `POST /users/search`) carry `tags`: every tag row as `{id, tag, verified, active, source, first_seen, last_seen}`, the active one first, loaded in one statement per page. `verified` is true when `bnet_account_id` is set. A user nested in another read carries `tags` empty.
- A batch alter of this table on SQLite drops the three expression indexes; the migration writes them back. See [migrations](../migrations.md).
- `GET /users` takes `no_discord=true`, the people with no login, and `tag_source=<source>`, the people who hold a tag row of that source. Both combine with `limit` and `offset`, and `X-Total-Count` counts the filtered rows.

# Merge

`POST /users/{id}/merge` `{into_user_id, dry_run}` is admin only. It moves person `{id}` into `into_user_id`: every column that holds a user id changes, in one transaction, and `{id}` is deleted. The columns are every foreign key to `users.id` in the table metadata, and three user id columns with no foreign key: `series.host_player_id`, `draft_series.host_player_id` and `series_side.user_id`. A new table with a foreign key to `users.id` joins the merge by itself.

The answer to a dry run is `{stops, removes, moves}`, each a list of plain sentences:

- `stops`: two rows that would share a unique key once the ids match, such as the same season signup, team season seat, round availability, fantasy bet or event entry, a seat in the same series, or a series the two play against each other. Both people having a Discord login is a stop too. A real run with any stop answers 409 with the same body and an `error`.
- `removes`: copies of one W3Champions fact. A duplicate [w3c_ladder_matches](w3c_ladder_matches.md) row or [w3cstats](w3cstats.md) row of `{id}` goes; of two [ladder_sync](ladder_sync.md) rows for one season, the older goes.
- `moves`: the rows that change, counted per table, such as `12 series` or `3 signups`.

The target keeps its profile and its active tag; the tags of `{id}` become its inactive tags, or the active one moves across when the target had none. A target with no login takes the Discord id and name of `{id}`. A real run answers the merged user read.
