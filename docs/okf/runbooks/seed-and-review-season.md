---
type: Runbook
title: Seed a database and build a review season
description: Load the private seed repository into a target, or build a season two accounts can click through on staging.
resource: ../../../app/core/seed.py
tags: [deploy]
generated: { by: claude-code/claude-fable-5-1, at: 2026-09-16T23:30:00Z }
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

The seed is a private repository of one CSV per table plus `logos/<team id>.<ext>` and a `manifest.json`. `uv run just vercel export-seed <dir> prod` writes it from production: every base table, rows ordered by primary key, NULL as `\N`, the secret settings blanked, and the manifest carrying the alembic revision of the database it came from. Run it after every schema change the seed must carry, then commit the directory to the seed repository.

`uv run just local seed`, `uv run just vercel seed <env>` and the azure recipe migrate the target, truncate every table, copy the CSVs with foreign keys off, set every sequence, and push the logos through the upload path. A directory with a manifest loads only when the database sits at the manifest's revision. A directory without one is a snapshot from before the event model, and the load rebuilds its GNL score system, leagues, stages, rounds and catalogue prices.

`just vercel seed` has no default environment, because it truncates: name `prod` or `staging` every time. For staging the recipe rebuilds the locked template first and then the shared database from it, so new previews start from the fresh copy. Open branch copies are untouched.

# Review season

`uv run just vercel review-season staging <reviewer discord id>` builds a season on staging where the two named accounts captain opposing teams, every account in the guild plays, and the pairings rotate each round. It becomes the current season and both accounts get an admin grant. The season is an event of the GNL league, with that league's entrant kind, so its teams stay in the league they belong to. Rosters, maps and the pick-and-ban order copy from the latest real season; the copied players are the rostered ones rated in the live W3Champions window, top window MMR first; badges come from the catalogue; the map rules are `fixed,loser,loser`. Running it again replaces the season. `season-badges` seeds badges into a season built another way.

# Which staging database

The staging connection string names the anchor database, which holds no app tables. The app serves from the shared staging database or from a branch copy. Resolve the name the way `api/preview_db.py` does before connecting by hand. See [the pitfall](../pitfalls/staging-url-wrong-db.md).
