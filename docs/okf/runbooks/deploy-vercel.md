---
type: Runbook
title: Deploy to Vercel
description: A merge to main deploys production and migrates in the build; staging mirrors main; previews use the staging database; the Hobby plan sets the limits.
resource: ../../../vercel.json
tags: [deploy]
generated: { by: claude-code/claude-fable-5-1, at: 2026-09-14T10:00:00Z }
stale_after: 2027-03-14T00:00:00Z
sources:
  - id: vercel-json
    resource: ../../../vercel.json
    title: The build command and the cron
  - id: vercel-just
    resource: ../../../just/vercel.just
    title: The Vercel recipes
  - id: readme
    resource: ../../../README.md
    title: Deploying to Vercel, and the variable table
---

# The normal path

1. Merge the pull request into `main`. Vercel builds production from that commit.
2. The build command runs `alembic upgrade head` against the production database before the new code is promoted. A failed migration stops the deploy and the previous build keeps serving.
3. A workflow force-pushes `staging` to the same commit, so the staging alias serves the merged code within seconds.
4. Check what production serves by asking the API for a field the change added, not by looking for a deployment row: a rate-limited day produces no row and production stays on the previous build.

# Environment

The README's variable table is the whole deploy list. Vercel adds `VERCEL_ENV` and `VERCEL_GIT_COMMIT_REF`. `DB_URL` in production and preview uses the transaction pooler on port 6543; the session pooler on 5432 holds 15 clients and a few warm functions fill it. See [the pitfall](../pitfalls/transaction-pooler.md). An environment change applies only to deployments built after it: redeploy.

# Previews

Every push builds a preview against the staging Supabase project. A branch with no migration uses the shared staging database; a branch with a migration gets a copy of the locked template and migrates it. A branch that does not know the shared database's revision fails its build with "rebase onto main". The copy is dropped when the branch is deleted. See [preview databases](../../PREVIEW-DATABASES.md). Previews sign in on the Clerk dev instance and are public.

# The recipes

`uv run just vercel deploy [prod|staging]` deploys the working tree; `logs`, `status`, `migrate`, `alembic`, `seed`, `import-maps`, `review-season`, `list` and `drop` are the rest. Run them only from the linked main checkout, never from a worktree: the `.vercel/` link folder is gitignored, and a run elsewhere creates a stray project that builds every push. A CLI deploy from a commit whose author is not a Vercel team member is silently blocked; export the tree with `git archive` first. Never run the Vercel CLI outside the recipes: without the token it starts a device authorization flow.

# The Hobby limits

- One cron per project, once a day. A more frequent schedule fails every deployment. Jobs that need minutes run from outside; see [jobs](../api/jobs.md).
- 100 deployment creations per rolling day across the account, and a daily build quota. A preview check that fails with the quota message is not a merge blocker.
- Deployment storage counts GB-months over retained deployments. Retention is set in the dashboard: a day for everything but production, a week for production.
- Function duration is 60 seconds. A season import from the API times out; import from a machine that runs the server.

# The cron

`vercel.json` schedules `GET /jobs/w3c-sync` at 04:00 UTC. Vercel may shift it by up to 59 minutes.
