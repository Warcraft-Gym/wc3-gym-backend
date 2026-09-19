---
type: Data Model
title: event
description: "One run of a league that people sign up for: a GNL season, a KOTH night, a cup or a sign-up list; the class is still named Season."
resource: ../../../../app/models/season.py
tags: [events, data]
generated: { by: claude-code/claude-fable-5-1, at: 2026-09-19T18:00:00Z }
verified: { by: process:test_okf, at: 2026-09-14T17:40:50Z }
sources:
  - id: model
    resource: ../../../../app/models/season.py
    title: Season
  - id: events
    resource: ../../../../app/services/events.py
    title: EventService writes the event columns and derives the phase
  - id: seasons
    resource: ../../../../app/services/seasons.py
    title: SeasonService writes the GNL columns, the map pool and the rounds
  - id: import
    resource: ../../../../app/services/season_import.py
    title: The workbook import
---

# Schema

The first block is the fields introduced for GNL, on `SeasonBase`. The second block is the common event fields. `EventPublic` carries both blocks so a GNL client does not need the deprecated season payload.

| Column | Type | Null | Meaning |
|---|---|---|---|
| `id` | INTEGER | no | Primary key. Every payload names it `season_id` or `event_id`. |
| `name` | VARCHAR | no | The name. Unique, case-insensitive, after trimming; the import matches a season by it. |
| `series_per_round` | INTEGER | no | How many series one fixture holds. Read only on an event of team entrants. |
| `pick_ban` | VARCHAR | yes | The veto order as steps joined by `\|`, each `<action>_<side>` such as `ban_A`. Null means no veto. |
| `start_date` | DATE | yes | First day. A GNL season keeps dates; a new round is placed a week after the one before it from here. |
| `end_date` | DATE | yes | Last day. Past it, a season with a missing result reads `overdue` and an event with no series reads `finished`. |
| `discordRole` | VARCHAR | yes | A Discord role id from the workbook. Written by the import and the export and exposed on event reads. Role sync uses [discord_role_binding](discord_role_binding.md). |
| `map_rules` | VARCHAR | yes | One rule per game, comma-joined: `fixed`, `loser`, `host`, `veto`. Null means the GNL default `fixed,loser,loser`. |
| `score_system` | VARCHAR | no | The scale series points are paid on: `standard` or `helpstone`. |
| `fantasy_grind` | BOOLEAN | no | On: the fantasy game offers the grind pick, a second team paid by achievement rank. |
| `signups_open` | BOOLEAN | no | Off: a signup is refused, or on a GNL season becomes a request an admin may grant. A finished event reads it off and refuses a signup whatever the column holds. |
| `scheduling_enabled` | BOOLEAN | no | Off: the event takes no availability answers. |
| `checkin_days` | INTEGER | yes | How many days before a round, or the event, its check-in opens. Null means the window never closes. |
| `league_id` | INTEGER | yes | The league this is a run of. Null for an event with no league. |
| `kind` | VARCHAR | no | `gnl`, `cup`, `koth` or `signup`. A GNL season is `gnl`. The shared services never branch on it. |
| `parent_id` | INTEGER | yes | The event this one feeds: a qualifier names the event it qualifies for. The parent lists it under `children`. |
| `signup_policy` | VARCHAR | no | `members` takes the session's player; `anyone` takes any battle tag. |
| `entrant_kind` | VARCHAR | no | `solo`, `team` or `drafted_teams`. Copied from the league when the event is created. A `drafted_teams` event takes no direct signup. |
| `published` | BOOLEAN | no | Off: a draft only an admin reads, and the phase is `draft`. |
| `checkin_enabled` | BOOLEAN | no | Off: no check-in is asked and every round stays open. |
| `early_checkin` | BOOLEAN | no | Whether a player may answer a round's check-in before its window opens. Not the same switch as `checkin_enabled`, which turns check-in off as a whole. On, the player may answer every round of the event that has not ended. |
| `round_end_zone` | VARCHAR | yes | An IANA time zone name, the zone a round of this event ends at midnight in. Null names no zone, and every round window of the event then stands in UTC. |
| `multi_entry` | BOOLEAN | no | On, a player may enter once per race and each row seeds on its own race; every KOTH night opens it. |
| `closed_at` | TIMESTAMP | yes | When an admin closed the event; a closed event reads finished, and a chain grows no further. |
| `page_url` | VARCHAR | yes | The event's landing or rules page, shown as one "Page" link. |
| `stream_url` | VARCHAR | yes | Where the event is streamed. Set by the admin form; answered on the event payload; no service reads it. |
| `discord_event_id` | VARCHAR | yes | The Discord message id of the event card last posted. A repost edits that message. Written by the card post. |
| `description` | VARCHAR | yes | Free text shown on the event page. |
| `starts_at` | TIMESTAMP | yes | When a cup or a KOTH night starts. A GNL season leaves it null and keeps its dates. |
| `min_games` | INTEGER | yes | The ladder games an entrant should have on its signup race. Warns on the entrant row; never refuses. |
| `min_games_seasons` | INTEGER | yes | How many of the newest W3C seasons `min_games` counts over, 1 or more. Null counts every synced season. |
| `mmr_max` | INTEGER | yes | The MMR an entrant should be under. Warns on the entrant row; never refuses. |
| `entrant_cap` | INTEGER | yes | The most live entrants the event takes. A signup past it is refused; no waiting list is kept. Null means no cap. |
| `region` | VARCHAR | yes | Where the event is played, as free text. Set by the admin form; answered on the event payload; no service reads it. |
| `fantasy_tier_cuts` | JSON | yes | The ascending MMRs each fantasy tier opens at, 1 to 5 of them. The tier count is one more. Null until a tier allocation is applied. |
| `fantasy_tiers_applied_at` | TIMESTAMP | yes | When the tiers were applied. An unpinned tier derives from the MMR on this date. |

# Keys and joins

Primary key `id`. Unique expression index on `lower(trim(name))`. Foreign keys: `league_id` to [league](league.md); `parent_id` to [event](event.md), set null on delete.

Pointed at by [event_stage](event_stage.md), [event_round](event_round.md), [event_division](event_division.md), [event_entrant](event_entrant.md) (`event_id` and `qualified_from_event_id`), [event_award](event_award.md), [matches](matches.md), [team_season](team_season.md), [team_season_captain](team_season_captain.md), [user_team_season](user_team_season.md), [user_season_signup](user_season_signup.md), [map_season](map_season.md), [round_availability](round_availability.md), [fantasy_teams](fantasy_teams.md), [fantasy_bets](fantasy_bets.md), [ladder_achievements](ladder_achievements.md), [discord_role_binding](discord_role_binding.md).

# Rules

- Two derived values ride on the payloads and are never stored: the GNL phase (`open`, `commenced`, `overdue`, `complete`) and the event phase (`draft`, `signups_open`, `checkin`, `seeded`, `running`, `finished`). See [GNL season](../../concepts/gnl-season.md) and [events module](../../concepts/events-module.md).
- The round count is not stored; the [event_round](event_round.md) rows are the count. `round_count`, `league_short_name` and `league_name` on the payloads are scalar subqueries.
- The GNL columns stay on `SeasonBase`; the event and deprecated season payloads both carry them. `tests/test_gnl_snapshot.py` pins the season payload. See [the decision](../../decisions/unified-event-model.md).
