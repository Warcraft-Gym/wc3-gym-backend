---
type: Convention
title: Git and pull requests
description: One branch and one pull request per change, squash merged to main, with a migration rule that keeps the previous deploy alive during the build.
tags: [git, process]
generated: { by: claude-code/claude-fable-5-1, at: 2026-09-14T10:00:00Z }
sources:
  - id: vercel-json
    resource: ../../../vercel.json
    title: The production build runs the migrations
  - id: preview-dbs
    resource: ../../PREVIEW-DATABASES.md
    title: Preview databases
---

# Branches

- Nothing is committed to `main` directly. Every change is a branch and a pull request with base `main`.
- Branch prefixes: `feature/`, `fix/`, `refactor/`, `chore/`. `chore/` is trivial upkeep only (a version bump, formatting). A new capability, including a new test suite or tooling, is `feature/`.
- Pull requests are squash merged. The pull request title and body become the commit on `main`, so write the body as the commit message: a plain summary paragraph first, short sections after it.
- A pull request references an issue as `Issue #37` or `Part of #37`. It never uses a closing keyword such as `Closes #37`: the issue stays open until the change is reviewed on production.

# Attribution

- Text an AI agent wrote in a pull request body starts with a note saying so. A commit an agent co-wrote ends with a `Co-Authored-By` trailer. The commit author is always the person whose clone made the commit; never override the author.
- Never claim that a person reviewed or approved something they did not.

# Migrations

- Alembic owns the schema. A model change ships with its migration, and `tests/test_migrations.py` fails when the migrated schema and the models differ.
- The production build runs `alembic upgrade head` while the previous deployment keeps serving. Every migration must work with the code before it and the code after it: add a column nullable or with a default; drop a column, or change its type, only in a later pull request, merged after the code that stopped reading it is live. See [the pitfall](../pitfalls/column-drop-two-deploys.md).
- One migration in flight at a time. Two open pull requests that both add a migration produce two Alembic heads on `main` after the second squash, which breaks CI and the staging migrate job. After merging `main` into a branch that carries a migration, run `uv run alembic heads` and re-point the revision before pushing.
- A pull request with a migration builds its preview against its own copy of the staging database. See [preview databases](../../PREVIEW-DATABASES.md).

# Checks before a merge

- CI runs lint, typecheck, a runtime-only import check and the tests on every pull request. `main` should be green by construction.
- A Vercel preview check that fails with a daily build quota message is not a code failure and does not block a merge. A check that names a real build error does.
- When two open pull requests touch one module, refresh the second from `main` and let CI run again before merging it.
