---
type: Decision
title: One KOTH entrant row per race
description: A player may enter a KOTH night on more than one race; each race is its own entrant row, listed once on the page, and the draw never pairs a player with himself.
tags: [koth]
generated: { by: claude-code/claude-fable-5-1, at: 2026-09-14T10:00:00Z }
sources:
  - id: source
    resource: Maintainers' decision, 2026-09-15
    title: KOTH per-race entry
---

# Decision

The entrant unique key widens from (event, user) to (event, user, race). A per-event switch, off by default and on for KOTH nights, allows the second row. Rows in the same bracket show once with the races as sub-rows. The chain draw gives a player one place and never pairs them with themself.

# Why

The unified entrant table had folded KOTH to one row per player per night. Multi-division entry is the feature; divisions are parallel, so a player in two never meets themself.

# Consequences

- The "races I may swap to" list for GNL is later; the per-series off race already records a swap.
