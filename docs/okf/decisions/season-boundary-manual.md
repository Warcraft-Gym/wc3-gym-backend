---
type: Decision
title: The season boundary is manual
description: The W3Champions season the MMR columns read is a pinned setting, edited by hand a few times a year, never derived automatically.
tags: [w3champions]
generated: { by: claude-code/claude-fable-5-1, at: 2026-09-14T10:00:00Z }
sources:
  - id: source
    resource: Maintainers' decision, 2026-08-25
    title: Keep the pin
---

# Decision

`current_w3c_season` stays a stored row. The derived default (the newest season from the API) applies only when the row is missing.

# Why

The derived value is wrong exactly when it would look smartest: the day a new season opens, every player has zero games in it, and every MMR column would go blank. Season management at the boundary is not a solved problem; relying on a human edit a few times a year is fine.

# Consequences

- Never propose auto-following the latest season, a staleness warning, or clearing the row.
- A stored value wins over a derived one, always.
See [settings](../concepts/settings-and-current-season.md).
