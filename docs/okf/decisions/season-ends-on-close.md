---
type: Decision
title: A season ends on the admin's close
description: A GNL season is complete only once an admin closes it; neither its last result nor its end date ends it, and it may be closed with results missing.
tags: [events]
generated: { by: claude-code/claude-opus-5-5, at: 2026-09-30T14:29:12Z }
sources:
  - id: source
    resource: Maintainers' decision, 2026-09-30
    title: Close a season by hand
---

# Decision

An event whose teams are drafted reads `finished`, and its season phase `complete`, only while `event.closed_at` is set. `POST /events/{id}/finish` sets it and `POST /events/{id}/reopen` clears it.

# Why

A season's series are drafted round by round, so every series it holds being scored means only that the next round is not drafted yet.

# Consequences

- Never derive the end of a season from its series or its end date. Past its end date an open season reads `overdue` and keeps running.
- A season may be closed while results are missing. The series stay unscored and `unscored_series` keeps counting them.
- A generated event keeps its derived end: its last stage holds every series it will play. See [the events module](../concepts/events-module.md#phase).
