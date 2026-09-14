---
type: Runbook
title: Back up and restore
description: There is no scheduled backup and no restore has been run; take a pg_dump by hand before a destructive migration, and know that the workbook export is not a restore.
resource: ../../../README.md
tags: [runbook, backup, postgres]
generated: { by: claude-code/claude-fable-5-1, at: 2026-09-14T10:00:00Z }
stale_after: 2027-03-14T00:00:00Z
sources:
  - id: review
    resource: Maintainers' backup review, 2026-09-10
    title: Findings on backup and restore
  - id: readme
    resource: ../../../README.md
    title: Season workbooks
---

# The state

- Production migrates inside the Vercel build with no dump first.
- A row delete drops its replays and pictures after the commit, so a database restore does not bring them back.
- `POST /export` covers about a third of the tables. It is a season snapshot and a test-data loader, not a restore path. The three import routes nothing calls stay until recovery is worked out.

# Before a destructive migration

1. Take a dump from a machine that holds the production URL: `pg_dump -Fc` with a client at least as new as the server. Older clients refuse.
2. Check the file is not empty.
3. Merge the migration.

No production credential lives in CI, by decision. The dump is a hand step.

# Restore

`pg_restore -d <database> <file>` on an empty database at the same migration revision, then the pictures and replays from their stores if they still exist. This path is untested.
