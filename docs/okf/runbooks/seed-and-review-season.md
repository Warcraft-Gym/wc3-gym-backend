---
type: Runbook
title: Seed a database and build a review season
description: Load the private seed repository into a target, or build a season two accounts can click through on staging.
resource: ../../../app/core/seed.py
tags: [deploy]
generated: { by: claude-code/claude-fable-5-1, at: 2026-09-16T19:30:00Z }
stale_after: 2027-03-14T00:00:00Z
sources:
  - id: seed
    resource: ../../../app/core/seed.py
    title: Seed a migrated Postgres from CSVs
  - id: review
    resource: ../../../app/services/review_season.py
    title: A season to review the player flows on
  - id: vercel-just
    resource: ../../../just/vercel.just
    title: seed, review-season, season-badges
---

# Seed

The seed is a private repository of one CSV per table plus `logos/<team id>.<ext>`, made from a production dump. `uv run just local seed`, `uv run just vercel seed staging` and the azure recipe migrate the target, truncate every table, copy the CSVs with foreign keys off, set every sequence, seed the achievement catalogue, and push the logos through the upload path.

**`just vercel seed` defaults to `prod`.** It truncates. Always name the environment: `uv run just vercel seed staging`. See [the pitfall](../pitfalls/seed-defaults-to-prod.md).

For staging the recipe rebuilds the locked template first and then the shared database from it, so new previews start from the fresh copy. Open branch copies are untouched.

# Review season

`uv run just vercel review-season staging <reviewer discord id>` builds a season on staging where the two named accounts captain opposing teams, every account in the guild plays, and the pairings rotate each round. It becomes the current season and both accounts get an admin grant. The season is an event of the GNL league, with that league's entrant kind, so its teams stay in the league they belong to. Rosters, maps and the pick-and-ban order copy from the latest real season; badges come from the catalogue; the map rules are `fixed,loser,loser`. Running it again replaces the season. `season-badges` seeds badges into a season built another way.

# Which staging database

The staging connection string names the anchor database, which holds no app tables. The app serves from the shared staging database or from a branch copy. Resolve the name the way `api/preview_db.py` does before connecting by hand. See [the pitfall](../pitfalls/staging-url-wrong-db.md).
