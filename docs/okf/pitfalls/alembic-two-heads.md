---
type: Pitfall
title: Two Alembic heads after a squash
description: Two branches that each add a migration on the same parent leave two heads on main after the second squash, breaking CI and the staging migrate job.
tags: [data]
generated: { by: claude-code/claude-fable-5-1, at: 2026-10-06T10:27:53Z }
sources:
  - id: source
    resource: ../../../tests/test_migrations.py
    title: The single-head test
---

# What happened

Two pull requests wrote a migration against the same revision. Both were approved and both squash-merged. `alembic upgrade head` refused on `main`, CI went red and the staging migrate job failed until a third pull request re-pointed one revision.

# The rule

One migration in flight at a time. After merging `main` into a branch that carries a migration, run `uv run alembic heads`; re-point the revision and commit before pushing. `tests/test_migrations.py` fails on two heads, so CI catches the same thing on the pull request.
