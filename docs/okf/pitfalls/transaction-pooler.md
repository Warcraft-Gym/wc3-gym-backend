---
type: Pitfall
title: The session pooler holds 15 clients
description: Serverless functions on the session pooler fill its 15 slots with idle connections and every other request answers Database error; use the transaction pooler on port 6543.
tags: [data, deploy]
generated: { by: claude-code/claude-fable-5-1, at: 2026-09-14T10:00:00Z }
sources:
  - id: source
    resource: ../../../app/core/db.py
    title: init_engine turns prepared statements off
---

# What happened

Twice. On production, 212 concurrent reads gave 83 answers of `500 {"error": "Database error"}`. On staging, one veto link failed with nobody else on the site. The log said `max clients reached in session mode - max clients are limited to pool_size: 15`. Every warm Vercel instance keeps up to five idle pooled connections, and in session mode each idle client holds one of the 15 slots per database.

# The rule

- `DB_URL` on every Vercel target uses the transaction pooler on port 6543. It held 60 idle clients in a test with no error.
- `init_engine` passes `prepare_threshold=None` for Postgres, because the transaction pooler rejects server-side prepared statements.
- Migrations and the `just` recipes may stay on 5432.
- An environment change applies only to deployments built after it; redeploy after editing it.
- Never fan out per-row requests from a page; a bulk route is one transaction.
