---
type: API Area
title: Response shapes
description: An entity inside another answer is its summary shape, bounded by the read's event; the detail comes only from the entity's own read, a write answers through that read, and every relationship refuses an on-the-spot load.
resource: ../../../app/models/user.py
tags: [api, data]
generated: { by: claude-code/claude-opus-5-5, at: 2026-09-26T20:17:19Z }
sources:
  - id: user
    resource: ../../../app/models/user.py
    title: UserSummaryPublic, UserListPublic and UserPublic
  - id: loads
    resource: ../../../app/services/users.py
    title: summary_loads and load_players
  - id: team
    resource: ../../../app/models/team.py
    title: TeamPublic and TeamRosterPublic
  - id: team-summary
    resource: ../../../app/models/team_summary.py
    title: TeamSummaryPublic
  - id: season
    resource: ../../../app/models/season.py
    title: SeasonSummaryPublic
  - id: roster-loads
    resource: ../../../app/services/teams.py
    title: roster_loads
  - id: fantasy-team
    resource: ../../../app/services/fantasy_teams.py
    title: FantasyTeamService.get and the team loads
  - id: fantasy-bet
    resource: ../../../app/models/fantasy_bet.py
    title: FantasyBet.loads
  - id: nesting
    resource: ../../../tests/test_response_shapes.py
    title: The nesting test
  - id: budget
    resource: ../../../tests/test_query_budget.py
    title: The statement and row pins
---

# The rules

1. **Summary when embedded, detail only from its own read.** Every entity has a summary shape and a detail shape. An entity inside another object is its summary. The detail comes only from the entity's own single read.
2. **A summary is bounded by the read's context.** It holds no all-time collection. Where a read is about one event, an embedded player's record is that event's record, and a team's roster is that event's roster.
3. **A write answers the entity's own GET, through the same function.** The write commits, then the service reads the row again by id with the read's own loads. No write builds its answer on a bare row.
4. **Every read declares its loads.** A shape reads a collection only when the read loaded it; an unloaded collection serves its empty value and never loads on the spot.
5. **Every relationship refuses an on-the-spot load.** Every `Relationship` of `User`, `Team`, `Series`, `DraftSeries`, `FantasyTeam`, `FantasyBet`, `Season` and the link rows in `app/models/relationships.py` carries `lazy="raise_on_sql"`: reading one the read did not load raises instead of sending a statement. A to-one relation already in the session answers without SQL. Code that needs a relation declares it in the read's loader (`summary_loads`, `roster_loads`, `_list_eager_options`, the entity's own read), reads the rows with its own statement (`event_rounds`, the pool's `map_season` rows), or reads a fixture once with `series_rules.fixture`, which keeps it on the series. A write reads the entity again with the read's loads (`populate_existing`) before it answers. A new row starts an empty collection itself (`maps=[]`, `casts=[]`), so the check that reads it sends no statement.
6. **Two tests and the lock hold the rules.** `tests/test_response_shapes.py` walks every schema a route answers with, from `/openapi.json`, and fails where a property embeds a shape of a registered entity other than its summary, or where a summary holds a list of entities. `tests/test_query_budget.py` pins the statements and rows of each read and of the write routes. The lock itself raises in any test that reads an undeclared relation.

# Shapes per entity

| Entity | Summary, when embedded | List row | Detail, from its own read |
|---|---|---|---|
| User | `UserSummaryPublic` | `UserListPublic`: the summary, less `record`, plus `signup_seasons`, `fantasy_tier_pinned`, `draft_position`, `draft_excluded` | `UserPublic`: the list row plus `gnl_stats` for every season and `trophies` |
| Team | `TeamSummaryPublic` | `TeamPublic`; `TeamRosterPublic` on an event's list | `TeamPublic` from its league; `TeamRosterPublic` from its event |
| Season | `SeasonSummaryPublic` | `SeasonPublic` | `EventPublic` |
| Series | `SeriesPublic`, the players as summaries | `SeriesPublic`, `StageSeriesRow` | `SeriesPublic` |
| Fantasy team | none | `FantasyTeamPublic`: the season and drafted team summaries, the captain and drafted players as player summaries | the same class |
| Fantasy bet | none | `FantasyBetPublic`: the season summary, `user` and `winner` as player summaries, `series` as the series list row | the same class |

The member variants `UserMemberListPublic` and `UserMemberPublic` add `discordTag` and `discordId` (see [users](../data/tables/users.md)). The nesting test allows no site to embed a detail shape. `TeamPublic`, `TeamRosterPublic` and `SeasonPublic` answer only at the top level, and `FantasyTeamPublic` and `FantasyBetPublic` too: the nesting test fails where any answer embeds them.

# The player summary

`UserSummaryPublic` holds the scalars of `UserReduced` (`id`, `name`, `battleTag`, `country`, `timezone`, `race`, `mmr`, the profile links, `w3c_synced_at`, `ladder_synced_at`), the ladder summary `race_mmrs` and `main_race`, `mmr_entered`, `signup_race`, `played_as`, `fantasy_tier`, `tags`, and `record`.

`record` is the player's `user_team_season` row in the read's event, as `UserTeamSeasonStatsPublic`: null outside an event context and null when the player holds no row there. The summary holds no `gnl_stats`. A list row and `UserPublic` serve no `record`; `UserPublic.gnl_stats` holds every season. `derived.fill_gnl_stats` fills the counts on the `record` of a summary and on every `gnl_stats` row of `UserPublic`.

| Embedded at | Event of the record | Record counts filled |
|---|---|---|
| `GET /series/{id}`, `POST /series`, `PUT /series/{id}`, `PUT /series/{id}/result-kind` and the draft promote: `player1` and `player2` | the series' event | yes |
| `GET /fantasy/bets/{id}`, every bet write and `POST`, `PUT /fantasy-bet`: the series players | the bet's season | yes |
| the same bets: `user` and `winner` | the bet's season | no |
| `GET /fantasy/teams/{id}`, every team write and `POST /fantasy-team`: the captain and the drafted players | the team's season | yes |
| the fantasy team list and search: the drafted players | each team's season | yes |
| the same lists: the captain | none, `record` null | |
| `GET /draft-series/{id}`, `GET /draft-series/match/{id}` and the draft writes | the match's season | no |
| `GET /events/{event_id}/entrants` | the event | no |
| `GET /events/{event_id}/teams`, `GET /events/{event_id}/teams/{team_id}` and the three event team writes: the roster and the captains | the event | yes |
| every series list, stage row, series side, and the bet list and search | none, `record` null | |

# The team and season shapes

`TeamSummaryPublic` (`app/models/team_summary.py`) holds `id`, `league_id`, `name`, `long_name` and `icon_url`. A match's teams, a stage row, an entrant's team, a captain fixture and a fantasy team's `drafted_team` embed it.

`TeamPublic` is the summary plus `seasons_info` (the standings of each event the team entered) and `discord_role_missing`. It answers `GET /leagues/{league_id}/teams/{team_id}`, the league team list, search and `basic` read, `GET /events/{event_id}/teams/basic` (whose `seasons_info` holds that event alone), and `POST` and `PUT /leagues/{league_id}/teams`, which answer through the single read after the commit.

`TeamRosterPublic` is `TeamPublic` plus `player_by_season` and `captains_by_season`, each with exactly one key, the event of the path, and a list of player summaries under it (empty when the team fields none). It answers `GET /events/{event_id}/teams`, `GET /events/{event_id}/teams/{team_id}`, and the three event team writes: `POST` and `DELETE /events/{event_id}/teams/{team_id}/players` and `PUT .../captains`, which answer through the event team read after the commit; the captains write adds `discord_role_missing`. `seasons_info` holds that event alone.

`SeasonSummaryPublic` holds `id`, `name`, `league_short_name`, `league_name`, `round_count`, `phase`, `start_date`, `end_date`, `round_end_zone`, `map_rules`, and `signup_race` and `played_as` where a signup row carries them. A match's season, on every match read and every series that carries its match, a fantasy team's and a bet's season, and each `signup_seasons` entry embed it. It holds no maps and no rounds.

# Loads

`summary_loads(event_id)` in `app/services/users.py` is the one loader of a player summary, relative to a `User`: the tags, and the `user_team_season` row of `event_id` alone (none without one), with no signups and no `w3cstats` rows. `signups=True` adds the signups a list row names; `window=<season>` loads the `w3cstats` rows of that live window for an entrant's MMR. The user list and search, the signups read and the entrants read compose it.

A single series, draft, bet or fantasy team read joins its players bare, then calls `load_players(session, ids, event_id)`, which reads those players again with `summary_loads(event_id)`: one statement for the players, one for their team rows and one for their tags. The event is known only once the row is read, so the reload comes after it.

`FantasyTeamService.get` is the one fantasy team read: the team with its season, drafted team and members bare, then `load_players` in the team's season. The team writes (`POST`, `PUT /fantasy/teams`, the players writes) and `POST /fantasy-team` answer through it once, after the commit. The team list and search join the same rows and add the team rows of the drafted players, so each carries the record of his team's season. The owner check, the reseat check and the score breakdown read the `fantasy_teams` row, not the answer.

`FantasyBet.loads()` is the one bet loader: the season, the bettor and winner bare, and the series with the loads of a series list row (`Series._list_eager_options(picks_only=True)`). `FantasyBetService.get` adds `load_players` in the bet's season; the bet writes and `POST`, `PUT /fantasy-bet` answer through it once. The bet list uses the same loader without the reload. The bet search keeps a lean row: the series with its players and bare match, no casts, picks or teams. The public bet writes check the series and the bet on their rows.

`roster_loads(event_id)` in `app/services/teams.py` is the one loader of an event roster, relative to a `Team`: the `user_team_season` and `team_season_captain` rows of `event_id` with their users under `summary_loads(event_id)`, and the `team_season` row of that event. The event team list and the single event team read compose it; no other team read loads a roster.
