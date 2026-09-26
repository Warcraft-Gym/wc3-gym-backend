---
type: Domain Concept
title: GNL season
description: Six drafted teams, five weekly rounds, one fixture per team pairing with captain-drafted series, and a phase that is derived from the series.
resource: ../../../app/models/season.py
tags: [events]
generated: { by: claude-code/claude-opus-5-5, at: 2026-09-23T04:29:00Z }
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
  - id: draft-board
    resource: ../../../app/services/draft_board.py
    title: The aggregated draft board read and the pair meetings read
---

# Shape

A GNL season is one event of the GNL league with one stage of format `gnl`. Six teams are drafted from the signups by the admins and the captains. The season runs about five rounds, one per week; each round has a date window and, when the map rules ask for it, a fixed map for game 1. Each team pairing in a round is a fixture (`matches`), and inside it the two captains draft about `series_per_round` player-versus-player series. The winner is the team with the most points over every fixture. There are no playoffs.

# API

The event routes are the canonical API for a GNL season. A client reads `GET /leagues`, selects the league whose `kind` is `gnl`, then reads `GET /events?league_id={league_id}`. The league id is enough to select the GNL; the event query does not also need `kind=gnl`.

`POST /events` creates a GNL season when `league_id` names the GNL league. The body may include `round_count`, `map_ids`, `series_per_round`, `map_rules`, `pick_ban`, `score_system` and `fantasy_grind`. The write creates the event, its single `gnl` stage, its rounds, its ordered map pool and its achievement rules in one transaction. The same event path updates and deletes it.

GNL management uses `/events/{event_id}/teams`, `/series`, `/maps`, `/rounds`, `/signups`, `/ladder`, `/ladder-sync`, `/fantasy` and `/achievements`. Team identities are managed under `/leagues/{league_id}/teams`; their rosters, captains, availability and event standings are under `/events/{event_id}/teams`. No `/seasons` route and no season-named team, series or fantasy route exists.

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
| `early_checkin` | whether a player may answer a round's check-in before its window opens; on, every round of the event that has not ended takes their answer |
| `round_end_zone` | the IANA zone a round ends at midnight in; null leaves each reader its own fallback. See [scheduling and availability](scheduling-and-availability.md). |
| `fantasy_grind` | whether the fantasy game offers the grind pick |
| `fantasy_tier_cuts`, `fantasy_tiers_applied_at` | the MMR cuts between fantasy tiers |
| `published` | off: a draft only an admin sees |

The number of rounds is not stored; the round rows are the count.

# Phase

A season's phase is derived on every read from its series and never stored: `open` while no series has started, `commenced` once one is scored or past its time, `overdue` when the end date passed with a result missing, `complete` when every series has a result. Every gate reads `phase`; nothing adds a date rule beside it. A `complete` season takes no signup. A `commenced` season takes a signup as a request an admin may grant.

The event payload answers the common phase word (`draft`, `signups_open`, `checkin`, `seeded`, `running`, `finished`) from `app/services/events.py`; [the events module](events-module.md) lists the rungs. `SeasonPublic`, which the GNL management writes answer and a match nests as `season`, keeps the four GNL phase words.

# Best of

Every GNL series is a Bo3. The backend supports any best-of through `map_rules` and the stage's `best_of`, but no GNL screen offers a choice. See [the decision](../decisions/bo3-only.md).

# The current season

The `settings` row `current_gnl_season` names the season the captain check, the role sync, the public signup form and the Discord bot read. When the row is missing, the newest season wins. See [settings](settings-and-current-season.md).

# Signups and the draft

A member signs up through `POST /signup` with a race and an MMR. The signup row carries `race`, `draft_position` (a hand-set place; null means sort by MMR), `draft_excluded` and `fantasy_tier`; `fantasy_tier_pinned` on the answer is derived from the tier and the season's apply date, never stored. See [user_season_signup](../data/tables/user_season_signup.md). A hand correction to the draft order is a position, never an adjusted MMR. See [the decision](../decisions/draft-order-rerank.md).

# The round draft

Inside a fixture the two captains write one shared draft of pairings, held in [draft_series](../data/tables/draft_series.md) until an admin publishes one. Either captain of the fixture creates, edits and deletes any pairing of it; only an admin publishes, and publishing writes the [series](../data/tables/series.md) row and deletes the draft in one transaction. Each pairing answers who wrote it and who last changed it, with the time of the change.

A fixture drafts up to the event's `series_per_round` pairings, counting published series and open drafts together. A pairing that replaces a published series is free of that count: it names an open series of the same fixture and keeps one of its two players, at most one draft replaces a series, and publishing it removes the replaced series with the booked time, the veto steps, the casts and the fantasy rows that hang on it. A read beside the draft names what that removal takes, so the admin's confirm can state it. A replaced series that holds a result or a replay is refused and nothing changes.

Each team keeps an advisory Ready mark in [match_draft_mark](../data/tables/match_draft_mark.md), which any change to a pairing clears; it never blocks publishing. A mark names one of the two teams of the fixture, so a write naming another team is refused, an admin's too. The same row holds when that team last read the pairings, written by its own call so a read never writes. The largest MMR difference the captains pair inside is a working value per fixture in [match_draft_state](../data/tables/match_draft_state.md), and the stage setting stands behind it. A GNL fixture refuses no repeat player: a player appears in more than one pairing of it unless a sibling series is drafted through a template.

# The draft board

One read fills the board a fixture is drafted on: `GET /matches/{match_id}/draft-board`, for a captain of either team of the fixture and for an admin. It answers figures, never rows, and it costs a constant number of statements, so a fixture of eight players a side costs what a fixture of two costs.

Per player of both rosters it carries the race he registered the event on, his W3C rating on that race, the ladder games behind it with the games-rule flag (`under_min_games`, or `no_w3c_stats` where nothing is stored), his wins and losses on that race against each opponent race inside the event's window, and his last ten counted ladder games as a string of `W` and `L`, newest first.

Per pairing of one player of each team it carries only what a client cannot work out: the hours both have open across the round, and, for two who have met, the score in the order of the pairing and the event they last met in. `hours` is null when the round has no dates: the hours are counted over the same round window the check-in and the free-time reads take, in the zone the event names (see [scheduling](scheduling-and-availability.md)), and the fallback to the event window is refused beyond 31 days, so the rest of the board still answers. The MMR difference is not sent; the client subtracts the two ratings. The board also carries the captain-draft stage's largest MMR difference, the event's `series_per_round`, and how many series the fixture has published and how many drafts stand open on it.

`GET /users/{user_a}/meetings/{user_b}` is the detail read behind one pairing, for a signed-in member: every finished series the two played, newest first, at most twenty, each with its date, its league and event, the score in the order of the path, the race each side played and the MMR each held going into it. The date is the series time and is null where the series carries none. That MMR is derived on read with `mmr_at` at the series time, else the first day of its round, on the race played: what the player took into his first rated match at or after it, else what his last rated match before it left him with. Only matches under his active battle tag count, inside the W3Champions seasons of the meeting's own event, plus the current one while that event's end has not passed; a side with no such match reads null. No column holds it. See [Ladder and achievements](ladder-and-achievements.md) and [w3c_ladder_matches](../data/tables/w3c_ladder_matches.md).

Both reads answer one caller, so both set `Cache-Control: private` and `Vary: Authorization`: no shared cache holds a copy, and the browser's own copy is keyed on the bearer that names the caller. See [the API overview](../api/overview.md).

# Import and export

`POST /import` reads one season from an exported workbook (ten sheets) and writes it in one transaction; `POST /export` writes it back. The GNL-only import resolves the GNL league first, then owns every imported team by that league and every roster by the imported event. It matches rows by natural keys (season name, battle tag, team name, series by fixture and players), so ids are never sent. `tests/data/` holds two season workbooks for the round-trip test.
