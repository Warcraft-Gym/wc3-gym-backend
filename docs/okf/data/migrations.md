---
type: Data Model
title: Migrations
description: Alembic owns the schema, the production build migrates while the old code serves, a preview gets its own database copy, and one head is allowed at a time.
tags: [alembic, migrations, postgres]
generated: { by: claude-code/claude-fable-5-1, at: 2026-09-14T10:00:00Z }
sources:
  - id: env
    resource: ../../../migrations/env.py
    title: The Alembic environment
  - id: test
    resource: ../../../tests/test_migrations.py
    title: The models and the migrations must agree
  - id: preview
    resource: ../../PREVIEW-DATABASES.md
    title: Preview databases
---

# Rules

- `alembic upgrade head` is the only thing that builds or changes the schema. The application never creates a table. The URL comes from `DB_URL`, the same variable the app reads.
- Each revision commits on its own, so a revision that adds an enum value can be followed by one that uses it.
- `tests/test_migrations.py` compares the migrated schema with the models, strictly, and fails on two heads.
- Write a migration with `uv run just local revision "message"` and read what autogenerate wrote: it also drops what the models no longer declare.

# Expand, then contract

The production build runs the migration while the previous deployment keeps serving. A migration therefore works with the code before it and after it:

1. Add a column nullable or with a server default. Rename a table by creating the new one and leaving a view under the old name.
2. Ship the code that reads the new shape.
3. Drop the old column or view in a later pull request, merged after step 2 is live.

The schema parity test is strict, so an unread column stays declared on the table class until the drop pull request. See [the pitfall](../pitfalls/column-drop-two-deploys.md).

# Heads

Two pull requests that each add a migration on the same parent produce two heads on `main` after the second squash, which breaks CI and the staging migrate job. One migration in flight at a time. After merging `main` into a branch that carries a migration, run `uv run alembic heads` and re-point the revision. See [the pitfall](../pitfalls/alembic-two-heads.md).

# Where migrations run

| Where | How |
|---|---|
| tests | on a temporary SQLite file, every run |
| local Docker | at every container start; a start with nothing to do logs no `Running upgrade` line |
| Vercel production | in the build command, before the new code is promoted; a failed migration stops the deploy |
| Vercel preview | in the build, against the branch's own copy of the staging template when the branch adds a migration, else the shared staging database. See [preview databases](../../PREVIEW-DATABASES.md). |
| staging template and shared database | a workflow on every push to `main` |

# Before a drop in production

There is no scheduled backup. Take a `pg_dump` by hand from a machine that holds the URL before any migration that drops or changes a column. See [backup and restore](../runbooks/backup-and-restore.md).

# SQLite

The tests run on SQLite, which needs a batch rebuild for some alterations. Never batch-alter `users` on SQLite: it drops the expression index on the Discord tag.
