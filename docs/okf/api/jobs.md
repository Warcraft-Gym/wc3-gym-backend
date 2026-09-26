---
type: API Area
title: Scheduled jobs
description: Five job routes behind a shared secret, two called daily by Vercel, one every five minutes by a Cloudflare Worker because a Vercel cron runs at most once a day, and two an operator reads for egress.
resource: ../../../app/api/routes/jobs.py
tags: [deploy]
generated: { by: claude-code/claude-opus-5-5, at: 2026-09-26T22:00:00Z }
sources:
  - id: jobs
    resource: ../../../app/api/routes/jobs.py
    title: The job routes and their guard
  - id: snapshot
    resource: ../../../app/services/egress_snapshot.py
    title: The egress snapshot and its windows
  - id: monitor
    resource: ../../../app/services/egress_monitor.py
    title: The egress monitor's levels and posts
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
| `GET /jobs/egress-snapshot` | copies pg_stat_statements into [egress_snapshot](../data/tables/egress_snapshot.md) on the server, deletes snapshots older than 35 days, and answers the window since the run before: rows, estimated MB, MB a day against the budget, and the ten statements that returned the most rows; then [the egress monitor](#the-egress-monitor) levels the cycle, the database size and the Vercel usage and posts to `DEV_ALERTS_WEBHOOK_URL` when it is set | Vercel cron at 00:00 UTC, shifted by up to 59 minutes |
| `GET /jobs/egress-snapshots?days=7` | one window per snapshot of the last `days` days (1 to 35), oldest first, totals only, with `Cache-Control: no-store` | an operator, with `just egress-days` against a local server |

All five check `Authorization: Bearer <CRON_SECRET>`. With `CRON_SECRET` unset every job route answers 503, so a deployment without the secret runs no job.

# The egress snapshot

The snapshot job fetches no statistics row to the function: the copy is an `INSERT ... SELECT`, and only the summary leaves the database. Without pg_stat_statements, on SQLite or on a Postgres where the view is not on the search path or cannot be read, the job answers 200 with `available: false` and a reason. Within an hour of the last snapshot it writes nothing and answers `available: true` with `skipped`, so a retry never turns a short window into a day rate. The estimate is rows times the bytes-per-row rate in `app/core/egress_stats.py`, and `over_budget` compares the day rate with `BUDGET_MB_PER_DAY` in `app/services/egress_snapshot.py`, the default of `just db check`.

# The egress monitor

After each run that writes a snapshot, `app/services/egress_monitor.py` levels the billing cycle, the database size and the Vercel usage, stores each level in its [monitor_state](../data/tables/monitor_state.md) row and posts Discord embeds to `DEV_ALERTS_WEBHOOK_URL`. Unset, it posts nothing. A skipped run posts nothing and keeps the levels.

- The cycle starts on day `CYCLE_START_DAY` of each month, UTC. A window counts toward the cycle its start falls in, so the run just after midnight on the first day bills the day before to the cycle before.
- The 3-day average is the MB of the windows that ended in the last 72 hours over their hours, times 24; with none, the last window. The projection is the cycle so far plus that average times the days left.
- `red` when the projection is over `RED_MB`, 90% of `CAP_MB`, the egress cap per cycle. `amber` when the last window is over `BUDGET_MB_PER_DAY`; amber only colours the digest. `unavailable` when the run could not read the statistics or raised. Otherwise `normal`.
- An alert posts when the level changes to `red` or to `unavailable`, never twice in a row. An alert Discord does not take, or one with the webhook unset, leaves the stored level as it was, so the next run posts it again. It tags `DEV_ALERTS_MENTION_USER_ID` when that is set to digits, and nobody otherwise.
- A recovery posts, silent, when the level changes from `red` or `unavailable` to `normal` or `amber`.
- The database size is the sum of `pg_database_size` over every database on the server but the templates, read on the server in one row, in MiB; when the role may not read the others, it is the size of the current database. It is `red` over `DB_RED`, 90% of `DB_CAP_MB`, the database size cap, and `normal` otherwise. It keeps its own row, `db_size`, and posts its own alert and recovery by the rules above, also after a run whose snapshot was unavailable. On SQLite it is skipped. A read that fails logs its error type, leaves the row as it was, and shows in the digest as `not read` with that type.
- With `VERCEL_USAGE_TOKEN` and `VERCEL_TEAM_ID` both set, a run reads the team's usage from the Vercel usage API over a rolling 30 days ending a minute before the run: function invocations, function GB-hours, edge requests and their cache hits, and outgoing bandwidth, each against its `VERCEL_*` constant, the included usage over 30 days. It keeps the `vercel` row: `red` when any meter is at `VERCEL_RED`, 80%, or over, with an alert naming the meters and a recovery when all are under it; `unavailable` when Vercel answers 401 or 403, with one alert until a read succeeds. Any other failure, a timeout or a 5xx, logs its error type and HTTP status, shows no Vercel field and leaves the row as it was. Either variable unset: no request, no field, no post.
- The digest posts, silent, after every run that writes a snapshot, after any alert or recovery. Before the first window it says the baseline is taken. It shows the database size and the Vercel usage when they were read, and a red one colours it red.
- The red alert and the digest link to the usage dashboards set in `DEV_ALERTS_SUPABASE_USAGE_URL` and `DEV_ALERTS_VERCEL_USAGE_URL`: the title opens the Supabase one, and a last Dashboards field lists each one set. A value that is not an https URL is ignored. The posts carry figures and links, and the dashboards draw the charts.
- The alert and the digest list the three routes of the [egress ledger](../data/tables/egress_ledger.md) with the most rows on the day the last window covers, and the digest is titled with that day.
- A run that raises posts its error type through the same state row. When the state cannot be read either, the alert posts without it.
- A failed post is logged with its error type and HTTP status and never fails the job. A monitor that raises is logged with its error type, and the route still answers the snapshot, which is already stored.

A run sends one request to Vercel when it is set up, and reads the database size, the three state rows, at most one window per day since the cycle start or the last 72 hours, whichever is earlier, and three ledger rows.

# Request cost headers

Every response carries `X-DB-Statements` and `X-DB-Rows`, the statements the request sent and the rows returned by reads plus rows changed by writes, and `X-Response-Bytes`, the content length or 0 for a streamed body. CORS exposes all three. One log line per request repeats them: `egress route=<template> method= status= statements= rows= bytes= ms=`. The W3Champions sync workers count toward the request that started them. `tests/test_query_budget.py` pins a rows-per-call ceiling for the list and detail routes it covers.

# Why the worker exists

The Vercel Hobby plan runs a cron once a day, and a `vercel.json` schedule that runs more often fails the whole deployment with no build log. A job that needs to run every few minutes gets a `/jobs/<name>` route here and something outside the backend calls it. The maintainers chose a Cloudflare Worker for the reminder; a GitHub Actions schedule was the other option, with the caveat that GitHub delays scheduled runs under load and switches a schedule off after 60 days without a push. See [the pitfall](../pitfalls/hobby-cron-daily.md).

# Adding a job

1. Add a route under `/jobs` that takes `credentials: Credentials` and calls `only_the_scheduler`.
2. Keep the work under the function limit; drain a bounded slice per call and let the next call continue, the way the sync does.
3. Schedule it outside, or in `vercel.json` if once a day is enough.
