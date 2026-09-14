---
type: Pitfall
title: just vercel seed defaults to production
description: The seed recipe truncates every table and reloads a dump, and its environment argument defaults to prod.
tags: [pitfall, seed, postgres]
generated: { by: claude-code/claude-fable-5-1, at: 2026-09-14T10:00:00Z }
sources:
  - id: source
    resource: ../../../just/vercel.just
    title: seed env="prod"
---

# The rule

Always name the environment: `uv run just vercel seed staging`. Read a recipe's defaults before running one that writes.
