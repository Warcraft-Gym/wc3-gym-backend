---
type: Decision
title: Derived, not stored
description: Every score, standing, rating and fantasy total is computed at read time; no rollup column and no recalculate button exists.
tags: [decision, scoring]
generated: { by: claude-code/claude-fable-5-1, at: 2026-09-14T10:00:00Z }
sources:
  - id: source
    resource: ../../../app/services/derived.py
    title: The read-time derivation
---

# Decision

Made 2026-08-19 and extended the same week to career and fantasy totals; the last stored rollup (per-player games, wins and losses) went on 2026-08-26. The rule lives once in `app/core/`, with a Python face and a SQL face pinned to each other, and `app/services/derived.py` fills every answer in a constant number of statements.

# Why

Stored derived values caused a recalculate button people forgot to press, a bug that wiped columns to null, write races between two recalculations, and stale numbers after every import. A read-time value is right by construction, and an import of any shape is safe without a step after it.

# Consequences

- Never add a stored points, score, rating or total column, and never a recalculate route.
- A new derived value goes in `derived.py` with a query-budget test.
- A cache is fine where a rollup was not: it is bounded by its TTL. Put it at the HTTP layer when public traffic asks for it, never in the database.
See [derived scores](../concepts/derived-scores.md).
