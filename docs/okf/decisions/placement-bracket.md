---
type: Decision
title: A placement bracket plays out every place
description: Every round splits each group into its winners and its losers, so the last round decides every place; a loss limit ends a run early, a field off the power of two closes its places up, and the final is a round of its own.
tags: [events]
generated: { by: claude-code/claude-opus-5-5, at: 2026-10-11T21:00:00Z }
sources:
  - id: source
    resource: Maintainers' decisions, 2026-10-05 and 2026-10-11
    title: The placement bracket of a cup
  - id: brackets
    resource: ../../../app/core/brackets.py
    title: placement_plan and PlaceGroup
  - id: engine
    resource: ../../../app/services/stage_engine.py
    title: placement_places and the placement table
---

# Decision

Since 2026-10-11, a stage may play the `placement` format. Every round splits each group into its winners and its losers, and a group is the range of places it plays for: 16 players play four rounds, and the last round decides every place. `event_stage.placement_lives` ends a player's run after that many losses, and the players who stop share the places of their group; null plays every place, and 1 is a single elimination with shared places.

# Why

A cup on one evening keeps every player playing until their place is settled, so a player who loses early still plays a full evening.

# Consequences

- The field pads to a power of two. A side facing an empty slot passes on without a series, so no series waits for a side that never comes, and the places close up over the padding: twelve players play for places 1 to 12.
- The series of places 1 and 2 in the last step is a round of its own, `Final`, with the `final` best-of; the other series of that step are the `Last round`, with `last_round`. A best-of is stored on the round, so the final needs its own round to play a longer series.
- No column stores a group. The plan follows from the field and `placement_lives`, so the engine draws it again over the series in the order the draw wrote them; the stage series read names each series' group in `place_from` and `place_to`, and the table puts every entrant at the first place its run holds.
- The awards pay the table's positions, so the players who share a range share its first place.
