---
type: Domain Concept
title: GNL season
description: Six drafted teams, five weekly rounds, one fixture per team pairing with captain-drafted series, and a phase that is derived from the series.
resource: ../../../app/models/season.py
tags: [events]
generated: { by: openai/gpt-6, at: 2026-09-15T22:29:05Z }
sources:
  - id: season-model
    resource: ../../../app/models/season.py
    title: The Season class and its phase
  - id: seasons-service
    resource: ../../../app/services/seasons.py
    title: SeasonService
  - id: gnl-events
    resource: ../../../app/services/gnl_events.py
    title: GNL event creation
  - id: scoring
    resource: ../../../app/core/scoring.py
    title: The series scoring rule
---

# Shape

A GNL season is one event of the GNL league with one stage of format `gnl`. Six teams are drafted from the signups by the admins and the captains. The season runs about five rounds, one per week; each round has a date window and, when the map rules ask for it, a fixed map for game 1. Each team pairing in a round is a fixture (`matches`), and inside it the two captains draft about `series_per_round` player-versus-player series. The winner is the team with the most points over every fixture. There are no playoffs.

# API

The event routes are the canonical API for a GNL season. A client reads `GET /leagues`, selects the league whose `kind` is `gnl`, then reads `GET /events?league_id={league_id}`. The league id is enough to select the GNL; the event query does not also need `kind=gnl`.

`POST /events` creates a GNL season when `league_id` names the GNL league. The body may include `round_count`, `map_ids`, `series_per_round`, `map_rules`, `pick_ban`, `score_system` and `fantasy_grind`. The write creates the event, its single `gnl` stage, its rounds, its ordered map pool and its achievement rules in one transaction. The same event path updates and deletes it.

GNL management uses `/events/{event_id}/teams`, `/series`, `/maps`, `/rounds`, `/signups`, `/ladder`, `/ladder-sync`, `/fantasy` and `/achievements`. Team identities are managed under `/leagues/{league_id}/teams`; their rosters, captains, availability and event standings are under `/events/{event_id}/teams`. Every `/seasons` route and every season-named team, series or fantasy route is a deprecated compatibility alias. A client can complete a GNL workflow without calling one.

# Fields on the season that drive behaviour

| Field | Meaning |
|---|---|
| `series_per_round` | how many series one fixture holds |
| `score_system` | `standard` or `helpstone`; the scale series points are paid on. See [derived scores](derived-scores.md). |
| `map_rules` | one rule per game: `fixed`, `loser`, `host`, `veto`. Null means the GNL default `fixed,loser,loser`. See [series reporting](series-reporting.md). |
| `pick_ban` | the veto order, side A and side B per step |
| `signups_open` | off: a signup is a request an admin may grant |
| `scheduling_enabled` | off: the season takes no availability answers |
| `checkin_enabled`, `checkin_days` | whether and when the round check-in opens |
| `fantasy_grind` | whether the fantasy game offers the grind pick |
| `fantasy_tier_cuts`, `fantasy_tiers_applied_at` | the MMR cuts between fantasy tiers |
| `published` | off: a draft only an admin sees |

The number of rounds is not stored; the round rows are the count.

# Phase

A season's phase is derived on every read from its series and never stored: `open` while no series has started, `commenced` once one is scored or past its time, `overdue` when the end date passed with a result missing, `complete` when every series has a result. Every gate reads `phase`; nothing adds a date rule beside it. A `complete` season takes no signup. A `commenced` season takes a signup as a request an admin may grant.

The event payload answers the common phase word (`draft`, `signups_open`, `checkin`, `seeded`, `running`, `finished`) from `app/services/events.py`; [the events module](events-module.md) lists the rungs. The deprecated season payload keeps its four phase words for compatibility.

# Best of

Every GNL series is a Bo3. The backend supports any best-of through `map_rules` and the stage's `best_of`, but no GNL screen offers a choice. See [the decision](../decisions/bo3-only.md).

# The current season

The `settings` row `current_gnl_season` names the season the captain check, the role sync, the public signup form and the Discord bot read. When the row is missing, the newest season wins. See [settings](settings-and-current-season.md).

# Signups and the draft

A member signs up through `POST /signup` with a race and an MMR. The signup row carries `race`, `draft_position` (a hand-set place; null means sort by MMR), `draft_excluded` and `fantasy_tier`; `fantasy_tier_pinned` on the answer is derived from the tier and the season's apply date, never stored. See [user_season_signup](../data/tables/user_season_signup.md). A hand correction to the draft order is a position, never an adjusted MMR. See [the decision](../decisions/draft-order-rerank.md).

# Import and export

`POST /import` reads one season from an exported workbook (ten sheets) and writes it in one transaction; `POST /export` writes it back. The GNL-only import resolves the GNL league first, then owns every imported team by that league and every roster by the imported event. It matches rows by natural keys (season name, battle tag, team name, series by fixture and players), so ids are never sent. `tests/data/` holds two season workbooks for the round-trip test.
