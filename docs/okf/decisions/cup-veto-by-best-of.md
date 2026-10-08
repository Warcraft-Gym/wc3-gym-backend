---
type: Decision
title: A cup vetoes by the best-of of each series
description: A cup names the best-of of each part of its bracket, and each series derives its veto from its own best-of and the pool; game 1 plays the map the veto leaves. GNL keeps its order and its fixed map.
tags: [events, maps]
generated: { by: claude-code/claude-opus-5-5, at: 2026-10-07T20:00:00Z }
sources:
  - id: source
    resource: Maintainers' decisions, 2026-10-07
    title: Cup map pool and best-of per bracket part
  - id: map-order
    resource: ../../../app/core/map_order.py
    title: cup_rules, cup_order and the pick queue
  - id: best-of
    resource: ../../../app/core/best_of.py
    title: The parts of a bracket
---

# Decision

Since 2026-10-07, a stage names the best-of of each part of its bracket in `event_stage.best_of_by_round`, counted back from the end (`quarterfinal`, `semifinal`, `final`; `upper_semifinal`, `upper_final`, `lower_semifinal`, `lower_final`, `grand_final`), and the draw writes it onto `event_round.best_of`. An event with `veto_by_best_of` derives the veto of each series from that series' best-of and the size of the pool: the sides ban in turn, the front side first, until as many maps are left as the series has games, then pick in turn one map for every game after the first. Game 1 plays the one map left (`decider`); every later game plays the next pick of the side that lost the game before.

# Why

A cup plays a short best-of early and a longer one in its finals, and its field size is unknown when it is created, so a part of the bracket names the best-of and never a round number. A cup has no round map and no admin to set one on the evening, so the veto alone decides every map, and one fixed order per event cannot serve a Bo1 and a Bo5 in the same bracket.

# Consequences

- The pool holds at least as many maps as the longest series of the event plays. The create, a stage write, a pool write and the draw refuse a smaller one and name the best-of that needs more.
- `PUT /events/{id}/maps` replaces a pool and refuses once a series of the event holds a veto step, so a board never changes under a veto.
- A GNL season leaves `veto_by_best_of` off and plays its `pick_ban` and its round map as before; with one pick a side, the pick queue offers what the single pick did.
- `decider` is never a stored map rule: a series answers it as its rules, derived on every read.
