---
type: Decision
title: One event model, kind modules on top
description: GNL, KOTH and community events share one data model; a kind that behaves differently gets its own module, and the shared engine never branches on kind.
tags: [events]
generated: { by: claude-code/claude-fable-5-1, at: 2026-09-14T10:00:00Z }
sources:
  - id: source
    resource: Maintainers' decision, 2026-09-13
    title: The unified event model
---

# Decision

One set of tables (league, event, stage, round, division, entrant, fixture, series, side, game) serves every kind of event. GNL keeps its draft, its captains' series draft and its fantasy game in their own services; KOTH keeps its night, its Twitch signup and its legacy payloads under `app/services/koth/`. The shared services and the stage engine read the rows and never test the kind.

# Why

The GNL season already ran unchanged on the renamed tables, pinned by the snapshot test. The features the maintainers want cross kinds: one upcoming list, one player history and head-to-head across every event, one check-in, one series, replay, cast and veto pipeline, one standings engine, one Discord post pipeline. A second schema would duplicate all of them. The real risk, complexity mixing, is answered by the no-branching rule, not by a second model.

One data model serves every kind; behaviour that differs by kind lives in a kind module.

# Consequences

- Never `if kind == "gnl"` inside a shared service. Put the behaviour in the kind module.
- A kind that needs its own columns gets a one-to-one side table when the columns get in the way, not before. Today the GNL-only columns still sit on the event row.
- Every shared-table migration keeps `tests/test_gnl_snapshot.py` green.
- External Discord servers are out of scope; a merged playoff across divisions is never a rule in the app.
