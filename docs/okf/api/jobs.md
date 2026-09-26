---
type: API Area
title: Scheduled jobs
description: Five job routes behind a shared secret, two called daily by Vercel, one every five minutes by a Cloudflare Worker because a Vercel cron runs at most once a day, and two an operator reads for egress.
resource: ../../../app/api/routes/jobs.py
tags: [deploy]
generated: { by: claude-code/claude-opus-5-5, at: 2026-09-26T10:00:00Z }
sources:
  - id: jobs
    resource: ../../../app/api/routes/jobs.py
    title: The job routes and their guard
  - id: snapshot
    resource: ../../../app/services/egress_snapshot.py
    title: The egress snapshot and its windows
  - id: vercel
    resource: ../../../vercel.json
    title: The daily crons
---

# The routes

| Route | Does | Called by |
|---|---|---|
| `GET /jobs/w3c-sync` | drains the stalest players' ladder matches and stats for 50 seconds, inside the 60 second function limit | Vercel cron at 04:00 UTC, shifted by up to 59 minutes |
| `GET /jobs/cast-reminders` | posts the reminder card for series that start soon | the Cloudflare Worker in the Discord adapter repository, every five minutes |
| `GET /jobs/egress?days=7` | the [egress ledger](../data/tables/egress_ledger.md) rows of the last `days` days (1 to 90), most rows first, with `Cache-Control: no-store` | an operator, with `just egress-routes` against a local server |
| `GET /jobs/egress-snapshot` | copies pg_stat_statements into [egress_snapshot](../data/tables/egress_snapshot.md) on the server, deletes snapshots older than 35 days, and answers the window since the run before: rows, estimated MB, MB a day against the budget, and the ten statements that returned the most rows | Vercel cron at 00:00 UTC, shifted by up to 59 minutes |
| `GET /jobs/egress-snapshots?days=7` | one window per snapshot of the last `days` days (1 to 35), oldest first, totals only, with `Cache-Control: no-store` | an operator, with `just egress-days` against a local server |

All five check `Authorization: Bearer <CRON_SECRET>`. With `CRON_SECRET` unset every job route answers 503, so a deployment without the secret runs no job.

# The egress snapshot

The snapshot job fetches no statistics row to the function: the copy is an `INSERT ... SELECT`, and only the summary leaves the database. Without pg_stat_statements, on SQLite or on a Postgres where the view is not on the search path or cannot be read, the job answers 200 with `available: false` and a reason. Within an hour of the last snapshot it writes nothing and answers `available: true` with `skipped`, so a retry never turns a short window into a day rate. The estimate is rows times the bytes-per-row rate in `app/core/egress_stats.py`, and `over_budget` compares the day rate with `BUDGET_MB_PER_DAY` in `app/services/egress_snapshot.py`, the default of `just db check`.

# Request cost headers

Every response carries `X-DB-Statements` and `X-DB-Rows`, the statements the request sent and the rows returned by reads plus rows changed by writes, and `X-Response-Bytes`, the content length or 0 for a streamed body. CORS exposes all three. One log line per request repeats them: `egress route=<template> method= status= statements= rows= bytes= ms=`. The W3Champions sync workers count toward the request that started them. `tests/test_query_budget.py` pins a rows-per-call ceiling for the list and detail routes it covers.

# Why the worker exists

The Vercel Hobby plan runs a cron once a day, and a `vercel.json` schedule that runs more often fails the whole deployment with no build log. A job that needs to run every few minutes gets a `/jobs/<name>` route here and something outside the backend calls it. The maintainers chose a Cloudflare Worker for the reminder; a GitHub Actions schedule was the other option, with the caveat that GitHub delays scheduled runs under load and switches a schedule off after 60 days without a push. See [the pitfall](../pitfalls/hobby-cron-daily.md).

# Adding a job

1. Add a route under `/jobs` that takes `credentials: Credentials` and calls `only_the_scheduler`.
2. Keep the work under the function limit; drain a bounded slice per call and let the next call continue, the way the sync does.
3. Schedule it outside, or in `vercel.json` if once a day is enough.
