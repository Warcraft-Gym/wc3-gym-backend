---
type: Runbook
title: Deploy to Vercel
description: A merge to main builds staging and migrates the staging database in that build; a GitHub Release builds production and migrates it in the build; the Hobby plan sets the limits.
resource: ../../../vercel.json
tags: [deploy]
generated: { by: claude-code/claude-opus-5-5, at: 2026-10-09T10:40:00Z }
stale_after: 2027-04-06T00:00:00Z
sources:
  - id: vercel-json
    resource: ../../../vercel.json
    title: The build command and the cron
  - id: release
    resource: ../../../.github/workflows/release.yml
    title: The release workflow
  - id: preview-db
    resource: ../../../api/preview_db.py
    title: The staging and branch databases
  - id: vercel-just
    resource: ../../../just/vercel.just
    title: The Vercel recipes
  - id: readme
    resource: ../../../README.md
    title: Deploying to Vercel, and the variable table
---

# A merge: staging

1. Merge the pull request into `main`. Vercel builds a preview of `main`, and that preview is staging. Production does not change.
2. The preview build runs `api/preview_db.py`, which brings the staging template and the shared staging database to head. The build that serves staging is the build that migrated its database.

# A release: production

1. `uv run just release` publishes a GitHub Release of `main`, tagged with the date (`v2026.10.09`; `uv run just release v2026.10.09.2` for a second one that day). The notes list the pull requests since the last release.
2. The `Release` workflow moves the `release` branch to the tagged commit. Release only a commit on `main`. `release` only moves forward, so roll back with Vercel, not with an older tag. A pre-release ships nothing.
3. Vercel builds production from `release`. The build runs `alembic upgrade head` against the production database before the new code is promoted. A failed migration stops the deploy and the previous build keeps serving.
4. Release the backend before the frontend: the backend stays compatible with the old frontend, and a new frontend may need the new backend.
5. Check what production serves by asking the API for a field the change added, not by looking for a deployment row: a rate-limited day produces no row and production stays on the previous build.

A release can carry several migrations. A migration that drops or changes a column ships in a release after the one whose code stopped reading it ([the pitfall](../pitfalls/column-drop-two-deploys.md)). A rollback is Vercel's Instant Rollback to the previous production deployment. It brings back the old code and leaves the schema as it is.

# Environment

The README's variable table is the whole deploy list. Vercel adds `VERCEL_ENV` and `VERCEL_GIT_COMMIT_REF`. `DB_URL` in production and preview uses the transaction pooler on port 6543; the session pooler on 5432 holds 15 clients and a few warm functions fill it. See [the pitfall](../pitfalls/transaction-pooler.md). An environment change applies only to deployments built after it: redeploy.

# Previews

Vercel builds `main` and `release` only (`git.deploymentEnabled` in `vercel.json`): a pull request builds no preview. A preview of another branch exists only when someone makes one by hand. A preview build picks its database in the staging Supabase project by its branch name: `main` migrates and uses the shared staging database; another branch with no migration uses the shared database; a branch with a migration gets a copy of the locked template and migrates it. A branch that does not know the shared database's revision fails its build with "rebase onto main". The copy is dropped when the branch is deleted. A preview deployed from an export of the tree carries no branch name, so the build picks no database for it: it shows that the code builds and starts, and nothing about data. See [preview databases](../../PREVIEW-DATABASES.md). Previews sign in on the Clerk dev instance and are public.

# The recipes

`uv run just vercel deploy [prod|staging]` deploys the working tree, and `deploy prod` goes around the release, so keep it for recovery; `url`, `logs`, `status`, `migrate`, `alembic`, `seed`, `export-seed`, `import-maps`, `review-season`, `season-badges`, `list` and `drop` are the rest. Run them only from the linked main checkout, never from a worktree: the `.vercel/` link folder is gitignored, and a run elsewhere creates a stray project that builds every push. A CLI deploy from a commit whose author is not a Vercel team member is silently blocked; export the tree with `git archive` first. Never run the Vercel CLI outside the recipes: without the token it starts a device authorization flow.

# The Hobby limits

- Each cron runs at most once a day. A more frequent schedule fails every deployment. Jobs that need minutes run from outside; see [jobs](../api/jobs.md).
- 100 deployment creations per rolling day across the account, and a daily build quota. A merge creates one preview deployment and a release one production deployment. A build that fails with the quota message is not a code failure.
- Deployment storage counts GB-months over retained deployments. Retention is set in the dashboard: a day for everything but production, a week for production.
- Function duration is 60 seconds. A season import from the API times out; import from a machine that runs the server.

# The cron

`vercel.json` schedules `GET /jobs/w3c-sync` at 04:00 UTC and `GET /jobs/egress-snapshot` at 00:00 UTC. Vercel may shift each by up to 59 minutes. Crons run on production deployments only, so staging never syncs the ladder.
