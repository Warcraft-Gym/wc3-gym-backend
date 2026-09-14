---
type: Pitfall
title: A column drop needs two deploys
description: The production build migrates while the previous code still serves, so a dropped column breaks every request of the old code until the promotion.
tags: [data]
generated: { by: claude-code/claude-fable-5-1, at: 2026-09-14T10:00:00Z }
sources:
  - id: source
    resource: ../../../vercel.json
    title: The build command
---

# What happened

A pull request created `series_cast` and dropped `series.caster` in the same migration. The old code's `SELECT series.*` would have failed for the whole build window. It was caught before the merge and split: create and copy first, drop in a later pull request merged after the first was live.

# The rule

Any `drop_column`, table drop or type change goes in its own pull request, merged only after the previous deploy is live. Keep the unread column declared on the table class until the drop, because the schema parity test is strict. Take a `pg_dump` first. A renamed table leaves a view under the old name for one deploy. See [migrations](../data/migrations.md).
