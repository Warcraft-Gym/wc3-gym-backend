---
type: Pitfall
title: A column drop needs two deploys
description: The production build migrates while the previous code still serves, so a dropped column breaks every request of the old code until the promotion.
tags: [data]
generated: { by: claude-code/claude-opus-5-5, at: 2026-10-09T10:40:00Z }
sources:
  - id: source
    resource: ../../../vercel.json
    title: The build command
---

# What happened

A pull request created `series_cast` and dropped `series.caster` in the same migration. The old code's `SELECT series.*` would have failed for the whole build window. It was caught before the merge and split: create and copy first, drop in a later pull request merged after the first was live.

# The rule

Any `drop_column`, table drop or type change goes in its own pull request, released only after the release whose code stopped reading the column is live. Two such pull requests between the same two releases put the drop in the same build as the code change, so the old code meets the dropped column. Keep the unread column declared on the table class until the drop, because the schema parity test is strict. Take a `pg_dump` first. A renamed table leaves a view under the old name for one deploy. See [migrations](../data/migrations.md).
