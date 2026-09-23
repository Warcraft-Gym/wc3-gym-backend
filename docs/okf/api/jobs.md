---
type: API Area
title: Scheduled jobs
description: Three job routes behind a shared secret, one called daily by Vercel, one every five minutes by a Cloudflare Worker, because the hosting plan allows one cron a day, and one that reads the egress ledger.
resource: ../../../app/api/routes/jobs.py
tags: [deploy]
generated: { by: claude-code/claude-opus-5-5, at: 2026-09-23T12:40:00Z }
sources:
  - id: jobs
    resource: ../../../app/api/routes/jobs.py
    title: The job routes and their guard
  - id: vercel
    resource: ../../../vercel.json
    title: The daily cron
---

# The routes

| Route | Does | Called by |
|---|---|---|
| `GET /jobs/w3c-sync` | drains the stalest players' ladder matches and stats for 50 seconds, inside the 60 second function limit | Vercel cron at 04:00 UTC, shifted by up to 59 minutes |
| `GET /jobs/cast-reminders` | posts the reminder card for series that start soon | the Cloudflare Worker in the Discord adapter repository, every five minutes |
| `GET /jobs/egress?days=7` | the [egress ledger](../data/tables/egress_ledger.md) rows of the last `days` days (1 to 90), most rows first, with `Cache-Control: no-store` | an operator, with `just egress-routes` against a local server |

All three check `Authorization: Bearer <CRON_SECRET>`. With `CRON_SECRET` unset every job route answers 503, so a deployment without the secret runs no job.

# Request cost headers

Every response carries `X-DB-Statements` and `X-DB-Rows`, what the request asked of the database, and `X-Response-Bytes`, the content length or 0 for a streamed body. CORS exposes all three. One log line per request repeats them: `egress route=<template> method= status= statements= rows= bytes= ms=`. `tests/test_query_budget.py` pins a rows-per-call ceiling for the list and detail routes it covers.

# Why the worker exists

The Vercel Hobby plan runs a cron once a day, and a `vercel.json` schedule that runs more often fails the whole deployment with no build log. A job that needs to run every few minutes gets a `/jobs/<name>` route here and something outside the backend calls it. The maintainers chose a Cloudflare Worker for the reminder; a GitHub Actions schedule was the other option, with the caveat that GitHub delays scheduled runs under load and switches a schedule off after 60 days without a push. See [the pitfall](../pitfalls/hobby-cron-daily.md).

# Adding a job

1. Add a route under `/jobs` that takes `credentials: Credentials` and calls `only_the_scheduler`.
2. Keep the work under the function limit; drain a bounded slice per call and let the next call continue, the way the sync does.
3. Schedule it outside, or daily in `vercel.json` if daily is enough.
