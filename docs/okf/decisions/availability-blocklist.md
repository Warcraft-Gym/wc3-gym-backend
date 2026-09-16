---
type: Decision
title: Ask when someone cannot play
description: Availability is collected as blocks, blank meaning fully open, and a block informs pairings without ever constraining them.
tags: [scheduling]
generated: { by: claude-code/claude-fable-5-1, at: 2026-09-14T10:00:00Z }
sources:
  - id: source
    resource: Maintainers' design, 2026-08-22
    title: The scheduling design
---

# Decision

Players state when they cannot play. There is no preferred time, no category of block, no inference from ladder activity. Blocks and one-off busy dates are time ranges in local time with a zone. A block never writes a round answer, never reorders a pairing and never refuses a time.

# Why

The league ran the obvious poll of best times for many seasons and dropped it: a statement of being busy is a fact, and a statement of being free is not.

# Consequences

- Never add a preferred state or a block category.
- Everything on a scheduling screen is a counted figure, never a judgement.
- The unit of the availability question is the round.
See [scheduling and availability](../concepts/scheduling-and-availability.md).
