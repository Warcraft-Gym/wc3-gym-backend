---
type: Data Model
title: Tables
description: The 41 tables, grouped by what they serve, with one line each.
tags: [schema, tables, postgres]
generated: { by: claude-code/claude-fable-5-1, at: 2026-09-14T10:00:00Z }
sources:
  - id: models
    resource: ../../../app/models
    title: One module per family
  - id: migrations
    resource: ../../../migrations/versions
    title: The migrations that built them
---

# Schema

## People and access

| Table | Class | Holds |
|---|---|---|
| `users` | `User` | a player: name, battle tag, Discord tag and id, main race, MMR, country, time zone, channels, avatar, ban date, two sync stamps |
| `clerk_account` | `ClerkAccount` | Clerk user id to Discord id, written by the first request of a login |
| `admin_grant` | `AdminGrant` | who administers the site, beside `ADMIN_DISCORD_IDS` |
| `settings` | `Settings` | the key-value rows; see [settings](../concepts/settings-and-current-season.md) |
| `user_block` | `UserBlock` | a standing weekly block, local time and zone |
| `user_busy` | `UserBusy` | a one-off busy range |

## Leagues and events

| Table | Class | Holds |
|---|---|---|
| `league` | `League` | what repeats: name, short name, kind, entrant kind, links |
| `event` | `Season` | one run of a league; the GNL season columns plus the event columns |
| `event_stage` | `EventStage` | one format over the entrants, with its rules |
| `event_round` | `DBEventRound` | one round: number, date window, fixed map |
| `event_division` | `EventDivision` | one MMR band that runs the event on its own |
| `event_entrant` | `EventEntrant` | a player or team in an event, with race, seed, division, check-in, withdrawal |
| `event_award` | `EventAward` | the frozen places of a finished event |
| `matches` | `Match` | a fixture: two teams in one round, optional fixed map |
| `series` | `Series` | one series: two players or two entrants, scores, time, host, off races, result kind, feeders |
| `series_side` | `SeriesSide` | the players of one side when a side holds more than one |
| `series_game` | `DBSeriesGame` | one game: winner side and map |
| `series_replay` | `DBSeriesReplay` | one replay slot per game, keyed into the bucket |
| `series_veto_step` | `DBSeriesVetoStep` | one taken veto step, with who entered it |
| `series_cast` | `SeriesCast` | a caster's claim on a series, channel and VOD |
| `draft_series` | `DraftSeries` | a captain's proposed series before an admin promotes it |
| `round_availability` | `DBRoundAvailability` | a player's answer for one round |

## Teams and rosters

| Table | Class | Holds |
|---|---|---|
| `teams` | `Team` | a team: name, long name, logo URL |
| `team_season` | `DBTeamSeason` | a team in a season, with its Discord role and coaches |
| `team_season_captain` | `DBTeamSeasonCaptain` | a captain seat |
| `user_team_season` | `DBUserTeamSeason` | a roster row |
| `user_season_signup` | `DBUserSeasonSignup` | a signup: race, MMR, draft position, fantasy tier |

## Maps

| Table | Class | Holds |
|---|---|---|
| `maps` | `Map` | a map: name, picture URL, ladder facts |
| `map_season` | `DBMapSeason` | a season's ordered pool |

## Fantasy

| Table | Class | Holds |
|---|---|---|
| `fantasy_teams` | `FantasyTeam` | a Fantasy Captain's team for one season: drafted team, race, grind pick |
| `fantasy_team_player` | `DBFantasyTeamPlayer` | a drafted player |
| `fantasy_bets` | `FantasyBet` | a stake on one series and a call |

## W3Champions

| Table | Class | Holds |
|---|---|---|
| `w3cstats` | `W3CStats` | per player, race and W3Champions season: MMR, wins, losses |
| `w3c_ladder_matches` | `W3CLadderMatch` | one ranked 1v1 match per GNL player, both races per side |
| `ladder_sync` | `LadderSync` | the (player, season) ledger of the match sync |
| `ladder_achievements` | `LadderAchievement` | a badge price for one season, or lifetime |
| `player_career_stats` | `PlayerCareerStats` | identity plus the historical baseline columns from before the app; the totals derive |

## Discord

| Table | Class | Holds |
|---|---|---|
| `discord_role_binding` | `DiscordRoleBinding` | a role kind and scope bound to a guild role |
| `discord_role_hidden` | `DiscordRoleHidden` | a guild role the binding page hides |
| `discord_post` | `DiscordPost` | a card the app posted and may edit |

# Views left for a deploy

A migration that renames a table leaves a view under the old name for one deploy, because the previous code keeps serving during the production build. The view is dropped in the next migration. See [migrations](migrations.md).
