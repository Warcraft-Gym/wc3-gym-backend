---
type: API Area
title: Response shapes
description: An entity inside another answer is its summary shape, bounded by the read's event; the detail comes only from the entity's own read, and a write answers through that read.
resource: ../../../app/models/user.py
tags: [api, data]
generated: { by: claude-code/claude-opus-5-5, at: 2026-09-26T18:16:00Z }
sources:
  - id: user
    resource: ../../../app/models/user.py
    title: UserSummaryPublic, UserListPublic and UserPublic
  - id: loads
    resource: ../../../app/services/users.py
    title: summary_loads and load_players
  - id: nesting
    resource: ../../../tests/test_response_shapes.py
    title: The nesting test
  - id: budget
    resource: ../../../tests/test_query_budget.py
    title: The statement and row pins
---

# The rules

1. **Summary when embedded, detail only from its own read.** Every entity has a summary shape and a detail shape. An entity inside another object is its summary. The detail comes only from the entity's own single read.
2. **A summary is bounded by the read's context.** It holds no all-time collection. Where a read is about one event, an embedded player's record is that event's record.
3. **A write answers the entity's own GET, through the same function.** The write commits, then the service reads the row again by id with the read's own loads. No write builds its answer on a bare row.
4. **Every read declares its loads.** A shape reads a collection only when the read loaded it; an unloaded collection serves its empty value and never loads on the spot.
5. **Two tests hold the rule.** `tests/test_response_shapes.py` walks every schema a route answers with, from `/openapi.json`, and fails where a property embeds a shape of a registered entity other than its summary, or where a summary holds a list of entities. `tests/test_query_budget.py` pins the statements and rows of each read and write.

# Shapes per entity

| Entity | Summary, when embedded | List row | Detail, from its own read |
|---|---|---|---|
| User | `UserSummaryPublic` | `UserListPublic`: the summary plus `signup_seasons`, `fantasy_tier_pinned`, `draft_position`, `draft_excluded` | `UserPublic`: the list row plus `gnl_stats` for every season and `trophies` |
| Team | none yet: a roster and a fantasy team embed `TeamPublic`; a match and an entrant embed `TeamReduced` | `TeamPublic` | `TeamPublic` |
| Season | none yet: a match, a fantasy team and a bet embed `SeasonPublic` | `SeasonPublic` | `EventPublic` |
| Series | `SeriesPublic`, the players as summaries | `SeriesPublic`, `StageSeriesRow` | `SeriesPublic` |
| Fantasy team, bet | none | `FantasyTeamPublic`, `FantasyBetPublic` | the same classes |

The member variants `UserMemberListPublic` and `UserMemberPublic` add `discordTag` and `discordId` (see [users](../data/tables/users.md)). The nesting test allows the sites that still embed a detail shape by name, with the reason: team rosters and captains, the fantasy captain, drafted players and drafted team, and the season of a match, a fantasy team and a bet.

# The player summary

`UserSummaryPublic` holds the scalars of `UserReduced` (`id`, `name`, `battleTag`, `country`, `timezone`, `race`, `mmr`, the profile links, `w3c_synced_at`, `ladder_synced_at`), the ladder summary `race_mmrs` and `main_race`, `mmr_entered`, `signup_race`, `played_as`, `fantasy_tier`, `tags`, and `record`.

`record` is the player's `user_team_season` row in the read's event, as `UserTeamSeasonStatsPublic`: null outside an event context and null when the player holds no row there. `gnl_stats` holds that same record as a one-entry list, or `[]`, for the consumers that read the list. A list row and `UserPublic` serve no `record`; `UserPublic.gnl_stats` holds every season.

| Embedded at | Event of the record | Record counts filled |
|---|---|---|
| `GET /series/{id}`, `POST /series`, `PUT /series/{id}`, `PUT /series/{id}/result-kind` and the draft promote: `player1` and `player2` | the series' event | yes |
| `GET /fantasy/bets/{id}` and every bet write: the series players | the bet's season | yes |
| the same bets: `user` and `winner` | the bet's season | no |
| `GET /draft-series/{id}`, `GET /draft-series/match/{id}` and the draft writes | the match's season | no |
| `GET /events/{event_id}/entrants` | the event | no |
| every series list, stage row, series side and bet list | none, `record` null | |

# Loads

`summary_loads(event_id)` in `app/services/users.py` is the one loader of a player summary, relative to a `User`: the tags, and the `user_team_season` row of `event_id` alone (none without one), with no signups and no `w3cstats` rows. `signups=True` adds the signups a list row names; `window=<season>` loads the `w3cstats` rows of that live window for an entrant's MMR. The user list and search, the signups read and the entrants read compose it.

A single series, draft or bet read joins its players bare, then calls `load_players(session, ids, event_id)`, which reads those players again with `summary_loads(event_id)`: one statement for the players, one for their team rows and one for their tags. The event is known only once the row is read, so the reload comes after it.
