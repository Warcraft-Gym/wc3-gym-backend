---
type: Decision
title: Off race per series, signup race per season
description: A player signs up on one race for the season; a series may record a different race played on one side, stored separately from the resolved race.
tags: [series]
generated: { by: claude-code/claude-fable-5-1, at: 2026-09-14T10:00:00Z }
sources:
  - id: source
    resource: Maintainers' decision, 2026-09-08
    title: Support the off-race series
---

# Decision

The signup race is the season race and never changes mid-season. A series stores `player1_off_race` / `player2_off_race` (null means the signup race) and answers the resolved `player1_race` / `player2_race` read-only.

# Why

A series recorded as one race when another was played is wrong data. A per-series fact after the game keeps bets, leaderboards and tiers consistent without a formal race change. Two names exist because two callers re-send the whole object; one shared name would pin the resolved race into the column.

# Consequences

- Never propose a dated race-change table or a mid-season signup race edit.
- Per-game race stays out until replay parsing exists.
- Season pages read the signup race alone, never `coalesce(signup_race, profile race)`: the profile race says nothing about a season.
