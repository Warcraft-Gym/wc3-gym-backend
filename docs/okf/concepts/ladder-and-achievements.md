---
type: Domain Concept
title: W3C ladder and achievements
description: Every ranked 1v1 match of a GNL player is stored once, scored per season on their signup race, and 24 badge rules run as one SQL union.
resource: ../../../app/services/ladder.py
tags: [w3champions]
generated: { by: openai/gpt-6, at: 2026-09-15T10:44:28Z }
sources:
  - id: ladder
    resource: ../../../app/services/ladder.py
    title: Store the ladder matches
  - id: ladder-rule
    resource: ../../../app/core/ladder.py
    title: The ladder scoring rule
  - id: achievements
    resource: ../../../app/core/achievements.py
    title: The 24 rules
  - id: rules-sql
    resource: ../../../app/core/achievement_rules.py
    title: The rules as SQL
  - id: parity
    resource: ../../../tests/test_achievement_parity.py
    title: SQL and the Python oracle agree
---

# What is stored

`w3c_ladder_matches` holds one row per GNL player per ranked 1v1 match, unique on (match id, user). Both the selected race and the rolled race are stored per side, because W3Champions filters on the selected race and Random counts everything. History starts at W3Champions season 23, where GNL S17 began.

`ladder_sync` is the ledger: one row per (player, W3Champions season) with `synced_at` and `complete`. A closed season marked complete is never fetched again; the open season is re-read from its stamp. The season and team "last synced" stamps derive as the earliest stamp across the roster and are never stored on the season.

Two sync pipelines exist and must not be confused: **matches** (this table, this ledger, the Sync Ladder button, `POST /events/{id}/ladder-sync` in chunks) and **MMR and stats** (`w3cstats`, `users.w3c_synced_at`, the older Sync W3C buttons, `POST /users/{id}/w3c-sync`). Different endpoints, different stamps.

# What is derived

- A match pays 3 points for a win and 1 for a loss. A match of `MIN_DURATION_S` or less pays nothing and is not a game. The rule has a Python and a SQL face in `app/core/ladder.py`.
- A player scores only on the race they signed the season up on; other races are stored and pay nothing; Random counts every race. The filter belongs in the read, never in the fetch.
- The season window is the GNL `start_date..end_date` on that race. MMR carries across a W3Champions season boundary unchanged, so the read needs no season logic.
- `GET /events/{id}/ladder` and `GET /users/{id}/ladder` answer the totals, per-day bars, MMR spans and badges. The event read is edge-cached; see [the pitfall](../pitfalls/edge-cache-cors.md).

# Achievements

The 24 rules follow the community achievement definitions, and `tests/test_achievement_parity.py` pins their totals against a recorded season. A rule is code in `app/core/achievements.py`; its condition runs as one select in `app/core/achievement_rules.py`, and one union answers every player at once. Three rules pay a variable amount. Two bucket by day. The rules are not what their names suggest; do not "fix" them against the name.

An achievement instance is a row of `ladder_achievements(season_id, rule_id, points)`: a price, nothing else. A season drops a rule by having no row. `SeasonService.add` seeds a new season with the default set. `season_id` null means lifetime, counted only from W3Champions season 26 onwards. Team badges are in `app/core/team_achievements.py`.

`tests/achievement_oracle.py` is the same rule set in Python. `tests/test_achievement_parity.py` runs both over random matches and over the same boundary case table. See [the pitfall](../pitfalls/test-drives-the-oracle.md).

# The W3Champions season pin

The `settings` row `current_w3c_season` pins the season the MMR columns read. The derived default (the newest season from the API) is wrong on the day a season opens, when every player reads as zero games. The pin is a deliberate hand edit a few times a year. Never auto-follow the latest season and never clear the row. See [settings](settings-and-current-season.md).

# Synchronisation

`GET /jobs/w3c-sync`, called by the daily Vercel cron with `CRON_SECRET`, drains the stalest players first for 50 seconds. The manual buttons stay and have no throttle. Every W3Champions call has a 10 second timeout and a throttled answer maps to a 502 with a fixed message.
