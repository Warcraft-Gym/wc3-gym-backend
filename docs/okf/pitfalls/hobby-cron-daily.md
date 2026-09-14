---
type: Pitfall
title: A Hobby cron runs once a day
description: A vercel.json schedule more frequent than daily fails every deployment with no build log, and production silently stays on the previous build.
tags: [pitfall, vercel, cron]
generated: { by: claude-code/claude-fable-5-1, at: 2026-09-14T10:00:00Z }
sources:
  - id: source
    resource: ../../../vercel.json
    title: The daily schedule
---

# What happened

Three merges produced no deployment at all. The GitHub status said only "Deployment failed". A CLI deploy printed the cause: Hobby accounts are limited to daily cron jobs, and the schedule ran every six hours.

# The rule

One daily schedule in `vercel.json`. Anything more frequent runs from outside against a `/jobs` route. After any merge that touches `vercel.json`, read the commit status; a failed Vercel context with no deployment row means the deployment creation failed, not the build. See [jobs](../api/jobs.md).
