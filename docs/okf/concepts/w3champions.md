---
type: Integration
title: W3Champions
description: The ranked ladder service the app reads MMR, per-race stats and match history from, with a timeout, a throttle answer, and two separate sync pipelines.
resource: ../../../app/services/w3c.py
tags: [w3champions]
generated: { by: claude-code/claude-fable-5-1, at: 2026-09-20T18:00:00Z }
sources:
  - id: client
    resource: ../../../app/services/w3c.py
    title: The client
  - id: ladder
    resource: ../../../app/services/ladder.py
    title: The match sync
  - id: fixtures
    resource: ../../../tests/data/w3c
    title: Captured pages the parser is tested on
---

# What is read

| Data | Endpoint family | Stored in | Trigger |
|---|---|---|---|
| MMR and wins and losses per race and season | player stats | `w3cstats`, `users.w3c_synced_at`, `users.mmr` | the Sync W3C buttons, `POST /users/{id}/w3c-sync`, `POST /events/{event_id}/teams/{team_id}/ladder-sync`, a KOTH signup of a tag with no fresh rating, the daily job |
| ranked 1v1 matches | match search, 100 per page | `w3c_ladder_matches`, the `ladder_sync` ledger | the Sync Ladder button, `POST /events/{id}/ladder-sync` in chunks, the daily job |
| the season list | ladder seasons | nothing; read when `current_w3c_season` is unset | on demand |
| the 1v1 map pool | maps | `maps`, paired with warcraft3.info by name and version | the ladder map import |

The base URL is the `w3c_url` setting, else the `W3C_URL` variable, else the built-in default. Every call has a 10 second timeout; a caller that answers a chat message passes a shorter one, and a KOTH signup uses five seconds. A refused burst raises `W3CThrottledError`, which answers 502 with a fixed message and logs at warning, not error: the other side pacing the app is not an incident.

# Facts that cost time to learn

- Season ids carry no dates. To find a player's matches in a window, walk the season ids backwards; a search without a season id answers nothing.
- The search filters on the race a player selected, and Random is a selected race. Store both the selected race and the rolled race per side.
- Offset paging has been seen to drop a row; a one-game difference against another source is not a bug here.
- A placement match carries no MMR at either end; it is unrated, not missing.
- MMR carries across a season boundary unchanged.

# The season pin

`current_w3c_season` pins the season the MMR columns read. It is a hand edit, on purpose. See [settings](settings-and-current-season.md).

# Load

A full season ladder sync outlives the function limit, so the route takes `offset` and `limit` and answers `next_offset`. The daily job drains the stalest players first for 50 seconds. The manual buttons have no throttle by decision.
