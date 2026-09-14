---
type: Decision
title: Draft order is a rerank, not an MMR
description: A hand correction to the draft order is a position on the signup row, never an adjusted MMR value.
tags: [decision, gnl]
generated: { by: claude-code/claude-fable-5-1, at: 2026-09-14T10:00:00Z }
sources:
  - id: source
    resource: Maintainers' decision, 2026-08-24
    title: Rerank instead of an adjusted MMR
---

# Decision

`user_season_signup.draft_position` holds a hand-set place; null means sort by MMR. The order composes over every signup, and a reversed sort keeps the relative order.

# Why

A number that pretends to be an MMR drifts from the real one and reopens the old GNL-MMR versus W3Champions-MMR problem. A player can be moved without being given a rating.

# Consequences

- Never add an override MMR.
- Before building a draft or ranking feature, read this and the season concept first.
