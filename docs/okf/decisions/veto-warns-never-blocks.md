---
type: Decision
title: The veto warns, it never blocks
description: A result may be reported without a veto record, but the form makes that hard with a strong warning; each game stores its winner and its map.
tags: [series]
generated: { by: claude-code/claude-fable-5-1, at: 2026-09-14T10:00:00Z }
sources:
  - id: source
    resource: Maintainers' decision, 2026-09-09
    title: The report form rules
---

# Decision

The veto is not a required input. A report without one gets a warning, possibly two, saying a veto really should be included. Each game is marked with a win and a loss, the replay upload sits beside its game, and a parser ticks the map and warns on a disagreeing winner without blocking.

# Why

A report is never blocked because a player lacks the recording or the veto went wrong. A series score alone is ambiguous at the game level: a third of GNL series go to a deciding game.

# Consequences

- Build the report against this. The open question is the wording of the warning, not whether it blocks.
- The board is still the one place a veto exists; a veto done elsewhere is entered after the fact on it, with who entered it.
