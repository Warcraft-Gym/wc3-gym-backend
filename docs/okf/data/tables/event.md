---
type: Data Model
title: event
description: "One run of a league that people sign up for: a GNL season, a KOTH night, a cup or a sign-up list; the class is still named Season."
resource: ../../../../app/models/season.py
tags: [events, data]
generated: { by: claude-code/claude-opus-5-5, at: 2026-10-22T07:56:14Z }
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

The first block is the fields introduced for GNL, on `SeasonBase`. The second block is the common event fields. `EventPublic` carries both blocks, so a GNL client reads one event payload.

| Column | Type | Null | Meaning |
|---|---|---|---|
| `id` | INTEGER | no | Primary key. Every payload names it `season_id` or `event_id`. |
| `name` | VARCHAR | no | The name. Unique, case-insensitive, after trimming; the import matches a season by it. |
| `series_per_round` | INTEGER | no | How many series one fixture holds. Read only on an event of team entrants. |
| `pick_ban` | VARCHAR | yes | The veto order as steps joined by `\|`, each `<action>_<side>` such as `ban_A`. Null means no veto. |
| `start_date` | DATE | yes | First day. A GNL season keeps dates; a new round is placed a week after the one before it from here. |
| `end_date` | DATE | yes | Last day. Past it, a GNL season that is not closed reads `overdue` and keeps running; an event of another shape reads `finished`. |
| `discordRole` | VARCHAR | yes | A Discord role id from the workbook. Written by the import and the export and exposed on event reads. Role sync uses [discord_role_binding](discord_role_binding.md). |
| `map_rules` | VARCHAR | yes | One rule per game, comma-joined: `fixed`, `loser`, `host`, `veto`. Null means the GNL default `fixed,loser,loser`. |
| `score_system` | VARCHAR | no | The scale series points are paid on: `standard` or `helpstone`. |
| `fantasy_grind` | BOOLEAN | no | On: the fantasy game offers the grind pick, a second team paid by achievement rank. |
| `signups_open` | BOOLEAN | no | Off: a signup is refused, or on a GNL season becomes a request an admin may grant. A draft and a finished event read it off and refuse a signup whatever the column holds. |
| `scheduling_enabled` | BOOLEAN | no | Off: the event takes no availability answers. |
| `checkin_days` | INTEGER | yes | `checkin_opens_minutes` in whole days, rounded down; null when that is null. A write that names `checkin_days` without the minutes sets the minutes to that many days. |
| `league_id` | INTEGER | yes | The league this is a run of. Null for an event with no league. |
| `kind` | VARCHAR | no | `gnl`, `cup`, `koth` or `signup`. A GNL season is `gnl`. The shared services never branch on it. |
| `parent_id` | INTEGER | yes | The event this one feeds: a qualifier names the event it qualifies for. The parent lists it under `children`. |
| `signup_policy` | VARCHAR | no | `members` takes the session's player; `anyone` takes any battle tag. |
| `entrant_kind` | VARCHAR | no | `solo`, `team` or `drafted_teams`. Copied from the league when the event is created. A `drafted_teams` event takes no direct signup. |
| `published` | BOOLEAN | no | Off: a draft only an admin reads, and the phase is `draft`. |
| `checkin_enabled` | BOOLEAN | no | Off: no check-in is asked and every round stays open. |
| `early_checkin` | BOOLEAN | no | Whether a player may check in before the window opens. Not the same switch as `checkin_enabled`, which turns check-in off as a whole. On, the player may answer every round of the event that has not closed, and check in to a cup or a round of a cup from the day they sign up. A new cup played over rounds turns it on. |
| `checkin_opens_minutes` | INTEGER | yes | How many minutes before the start the check-in opens: before midnight on a dated round's first day, in `round_end_zone` or UTC, before `starts_at` on a cup, a KOTH night or a sign-up list, before `cup_leg.starts_at` on a round of a cup. Null opens it from sign-up. A new cup that names no window takes 120; any other new event `checkin_days` in minutes. |
| `checkin_closes_minutes` | INTEGER | yes | How many minutes before the start the check-in closes, 0 or more and below `checkin_opens_minutes`; 0 closes a dated round at its start. Null closes a dated round when it ends, and a cup or a round of a cup at its draw. A close by hand or the event's close shuts it earlier. |
| `checkin_closed_at` | TIMESTAMP | yes | When a runner closed the event's own check-in by hand with `POST /events/{id}/checkin/close`, cleared by `POST /events/{id}/checkin/reopen`; a second close keeps the first time. The check-in closes at the earliest of the early close, this time, `closed_at` and `cancelled_at`. An event that checks in per dated round or per round of a cup, or whose check-in is off, has no close by hand: the close refuses it with 400. The reopen clears the time on any event, because every dated round of the event reads it. |
| `round_end_zone` | VARCHAR | yes | An IANA time zone name, the zone a round of this event ends at midnight in. Null names no zone: the check-in window and the free-time reads then stand at UTC midnights, and the check-in hint and the out-on-blocked-times flag read the round in the player's own zone. |
| `multi_entry` | BOOLEAN | no | On, a player may enter once per race and each row seeds on its own race; every KOTH night opens it. |
| `closed_at` | TIMESTAMP | yes | When a runner closed the event, stamped by `POST /events/{id}/finish`, `POST /events/{id}/cancel` and the KOTH close, cleared by `POST /events/{id}/reopen`. A closed event reads finished, a closed GNL season reads `complete`, and a chain grows no further. Nothing else ends an event whose teams are drafted. |
| `cancelled_at` | TIMESTAMP | yes | When a runner called the event off with `POST /events/{id}/cancel`, which also stamps `closed_at` and deletes the award rows. A cancelled event reads finished, takes no signup and refuses a finish; `POST /events/{id}/reopen` clears both stamps. |
| `page_url` | VARCHAR | yes | The event's landing or rules page, shown as one "Page" link. |
| `stream_url` | VARCHAR | yes | Where the event is streamed. Set by the admin form; answered on the event payload; no service reads it. |
| `discord_event_id` | VARCHAR | yes | The Discord message id of the event card last posted. A repost edits that message. Written by the card post. |
| `description` | VARCHAR | yes | Free text shown on the event page. |
| `starts_at` | TIMESTAMP | yes | When a cup or a KOTH night starts. A GNL season leaves it null and keeps its dates. |
| `min_games` | INTEGER | yes | The ladder games an entrant should have on its signup race. Warns on the entrant row; refuses only where `eligibility_required` is on. |
| `race_games_min` | INTEGER | yes | The lifetime W3Champions games a race needs before its rating counts for eligibility; the best rating among those races is checked, and a player with no such race is refused. Null checks the race of the signup alone. |
| `min_games_seasons` | INTEGER | yes | Narrows the live W3C window `min_games` counts over (the current season and the one before it), 1 or more: 1 counts the current season alone; null, 2 and more count the window. |
| `mmr_min` | INTEGER | yes | The MMR an entrant should be at or above on its signup race, no higher than `mmr_max`. Warns on the entrant row (`under_mmr_min`); refuses only where `eligibility_required` is on. |
| `mmr_max` | INTEGER | yes | The MMR an entrant should be under. Warns on the entrant row; refuses only where `eligibility_required` is on. |
| `eligibility_required` | BOOLEAN | no | On: a signup, self or by hand, is refused unless W3Champions rates the player's active battle tag on the signup race, the rating sits inside `mmr_min` and `mmr_max` and the games reach `min_games`. The rating is read again from W3Champions first, at most once an hour per player. Off by default. |
| `team_size` | INTEGER | yes | How many players a team of a team cup fields, 2 to 4; the cup plays real team games. Null is an event of single players. |
| `veto_by_best_of` | BOOLEAN | no | On: each series derives its veto from its own best-of and the pool, and game 1 plays the map the veto leaves, see [the decision](../../decisions/cup-veto-by-best-of.md). A cup turns it on; off plays `pick_ban` and the round map. Off by default. |
| `bnet_required` | BOOLEAN | no | On: a player enters only with an active battle tag verified through Battle.net, with or without `eligibility_required`, and the event takes members only. A player already in when it turns on stays, and their row warns `not_verified`. Off by default. |
| `hide_seeds` | BOOLEAN | no | On: the entrants read and the stage series read answer seed numbers only to the event's admins and organizers; every other reader gets null, and the entrants in signup order. Off by default. |
| `entrant_cap` | INTEGER | yes | The most live entrants the event takes. A signup past it is refused, except on a cup, which puts it on its waitlist (`event_entrant.waitlisted_at`). Null means no cap. |
| `entrant_min` | INTEGER | yes | The fewest entrants the event is played with, at least 2. The draw of the first stage refuses while fewer would play: every entrant that has not withdrawn, across the divisions. A later stage is never held to it. Null means no minimum. |
| `region` | VARCHAR | yes | Where the event is played, as free text. Set by the admin form; answered on the event payload; no service reads it. |
| `fantasy_tier_cuts` | JSON | yes | The ascending MMRs each fantasy tier opens at, 1 to 5 of them. The tier count is one more. Null until a tier allocation is applied. |
| `fantasy_tiers_applied_at` | TIMESTAMP | yes | When the tiers were applied. An unpinned tier derives from the MMR on this date. |

# Keys and joins

Primary key `id`. Unique expression index on `lower(trim(name))`. Foreign keys: `league_id` to [league](league.md); `parent_id` to [event](event.md), set null on delete.

Pointed at by [event_stage](event_stage.md), [event_round](event_round.md), [event_division](event_division.md), [event_entrant](event_entrant.md) (`event_id` and `qualified_from_event_id`), [event_award](event_award.md), [matches](matches.md), [team_season](team_season.md), [team_season_captain](team_season_captain.md), [user_team_season](user_team_season.md), [user_season_signup](user_season_signup.md), [map_season](map_season.md), [round_availability](round_availability.md), [fantasy_teams](fantasy_teams.md), [fantasy_bets](fantasy_bets.md), [ladder_achievements](ladder_achievements.md), [event_organizer](event_organizer.md), [discord_role_binding](discord_role_binding.md), [historical_participant](historical_participant.md), [koth_history_event](koth_history_event.md), [koth_history_series](koth_history_series.md), [event_video](event_video.md), [cup_settings](cup_settings.md), [cup_team](cup_team.md), [cup_team_invite](cup_team_invite.md), [cup_leg](cup_leg.md), [cup_occurrence](cup_occurrence.md).

Every key that points at an event cascades, except `parent_id` and `event_entrant.qualified_from_event_id`, which set null. The keys that tie a [draft_series](draft_series.md) row to its fixture and a [fantasy_team_player](fantasy_team_player.md) row to its fantasy team cascade too. `DELETE /events/{id}` therefore deletes the event with every row under it: its stages, rounds, fixtures, series, drafts, entrants, signups, captains, availability answers, fantasy teams and their players, bets and achievement prices, and a cup's settings, teams, invites, rounds, series and its place in a recurring rule. A cup also takes its [discord_post](discord_post.md) rows and the [cup_recurrence](cup_recurrence.md) it was the last cup of. The users, teams and maps it named stay. A runner of the event deletes it: an admin, or one of its organizers.

# Rules

- Two derived values ride on the payloads and are never stored: the GNL phase (`open`, `commenced`, `overdue`, `complete`) and the event phase (`draft`, `signups_open`, `checkin`, `seeded`, `running`, `finished`). See [GNL season](../../concepts/gnl-season.md) and [events module](../../concepts/events-module.md).
- The round count is not stored; the [event_round](event_round.md) rows are the count. `round_count`, `league_short_name` and `league_name` on the payloads are scalar subqueries.
- The GNL columns stay on `SeasonBase`; `EventPublic` and `SeasonPublic` both carry them. `tests/test_event_season_parity.py` pins the GNL fields on `EventPublic`. See [the decision](../../decisions/unified-event-model.md).

For an imported archive, `closed_at` is the administrative import closure, not a reported historical finish time. Date-only sources fill the calendar dates and leave `starts_at` null. Played series with unavailable results count toward completion.
