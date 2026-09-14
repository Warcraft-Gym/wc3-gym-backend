---
type: Pitfall
title: The ladder table is the egress driver
description: Reading a whole season window of ladder matches on every view grows through a season and multiplies with viewers.
tags: [pitfall, postgres, egress]
generated: { by: claude-code/claude-fable-5-1, at: 2026-09-14T10:00:00Z }
sources:
  - id: source
    resource: ../../../app/services/ladder.py
    title: The match reads
---

# What happened

Measured on production with `pg_stat_statements`: about 230 of 311 MB of query results came from `w3c_ladder_matches`. A season ladder view read every match in the window, about 1.4 MB, and four pages loaded it. The per-player dedupe read on sync fetched all of a player's stored ids to skip a handful of new matches.

# The rule

- Derive badges and totals in SQL, which is what the achievement rules do now, so a read returns badges, not matches.
- Scope a dedupe read to the ids in hand; the unique index already guards duplicates.
- Storing history is cheap; reading it per view is the cost. Storage scope is a constant (`FIRST_W3C_SEASON`). Do not propose Python rule evaluation over the rows again.
