---
type: Decision
title: A missing replay warns, it never blocks
description: Every game should carry its replay, and the report pushes hard for it, but a result is saved without one when the file is missing, bad or the bucket fails.
tags: [series, storage]
generated: { by: claude-code/claude-opus-5-5, at: 2026-09-29T12:00:00Z }
sources:
  - id: source
    resource: Maintainers' decision, 2026-09-29
    title: Replays are optional on a report
---

# Decision

A replay per game played is expected, not required. The report saves the result and answers `replays_missing`, the games left without a replay; the dashboard and the Discord command warn with that list. A file that is missing, is not a replay, is over the size cap, or cannot be checked because the bucket fails leaves only its own game without a replay. Replacing one game's replay after the result still needs its file.

# Why

A result must never wait on a file or on the bucket being up. The replay still belongs with every game, so the forms make leaving one out hard.

# Consequences

- The report form marks every played game without a file, and saving without them asks once before it goes through.
- A missing replay is added later through the same form, which replaces that one game.
