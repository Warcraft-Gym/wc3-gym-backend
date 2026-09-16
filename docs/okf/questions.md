---
type: Guide
title: Start here by question
description: The questions a new contributor or an agent asks first, each with the concept that answers it; the list is also the benchmark the bundle is read against.
tags: [tooling]
generated: { by: claude-code/claude-fable-5-1, at: 2026-09-14T17:00:00Z }
sources:
  - id: index
    resource: index.md
    title: The bundle map
---

# Running and changing the code

- How do I run the backend on my machine? [Run locally](runbooks/run-locally.md).
- How do I add or drop a column without breaking the running deploy? [Migrations](data/migrations.md), then [a column drop takes two deploys](pitfalls/column-drop-two-deploys.md).
- How do I write a new model with its Create, Update and Public shapes? [Model families](data/model-families.md).
- Which layer may call which? [Layering](conventions/layering.md).
- How do I deploy, and what runs on a push to main? [Deploy on Vercel](runbooks/deploy-vercel.md).
- How do I back up or restore the production database? [Backup and restore](runbooks/backup-and-restore.md).
- Why must every datetime be timezone-aware UTC? [Datetimes are UTC](pitfalls/datetimes-are-utc.md).
- What goes wrong with the Supabase transaction pooler? [The transaction pooler](pitfalls/transaction-pooler.md).

# The domain

- What is a fixture, a series, a game, a round? [Vocabulary](concepts/vocabulary.md).
- What does a GNL season's phase mean and how is it computed? [GNL season](concepts/gnl-season.md).
- How does an admin take an event from a new league to awards? [Events module](concepts/events-module.md).
- How is a KOTH night opened, run and closed? [KOTH night](concepts/koth.md).
- Why are standings and points computed on every read and never stored? [Derived, not stored](decisions/derived-not-stored.md), with the rule in [derived scores](concepts/derived-scores.md).
- How does a player report a result with replays? [Series reporting](concepts/series-reporting.md).
- Why does the veto warn but never block a report? [The veto warns, never blocks](decisions/veto-warns-never-blocks.md).
- How are fantasy points computed? [Fantasy league](concepts/fantasy.md).
- Where is the current season decided? [Settings and the current season](concepts/settings-and-current-season.md).
- Which columns does the `series` table have? [series](data/tables/series.md).

# Access and integrations

- Which roles exist and who may write? [Roles and permissions](concepts/roles-and-permissions.md).
- How does a Clerk session become a role on a request? [Authentication](api/auth.md).
- What is the shape of every error response, and how does paging work? [API overview](api/overview.md).
- Which routes does the web app call, and which tests pin them? [Consumers](api/consumers.md).
- Which scheduled jobs exist and when do they run? [Scheduled jobs](api/jobs.md).
- How do I set up the Discord bot for a server? [Discord setup](runbooks/discord-setup.md).
- Why does the app pace its Discord card edits? [The Discord rate limit](decisions/discord-rate-limit.md).
- How do the two W3Champions syncs differ? [W3Champions](concepts/w3champions.md).
- What are the badge rules and where do they run? [W3C ladder and achievements](concepts/ladder-and-achievements.md).
- Why are logos and map pictures URLs and not bytes? [Pictures as URLs](decisions/pictures-as-urls.md).

# The benchmark

A reader who starts at [the bundle map](index.md) should reach each answer in two hops: the map names the directory, the directory index names the concept. When a question here misses, the fix is the index line, not this list.
