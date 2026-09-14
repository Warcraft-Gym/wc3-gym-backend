---
type: Runbook
title: Run locally
description: Install with uv, copy the example environment, start Postgres and the backend with just, run the tests.
tags: [runbook, local, uv, just]
generated: { by: claude-code/claude-fable-5-1, at: 2026-09-14T10:00:00Z }
sources:
  - id: readme
    resource: ../../../README.md
    title: Project setup and running the application
  - id: local
    resource: ../../../just/local.just
    title: The local recipes
---

# Steps

1. Install `uv`. Run `uv sync`. That installs the right Python, the dependencies and the dev tools, including `just`.
2. `cp .env.example .env`. The example holds development values; the deployment reads none of this file.
3. Run the tests: `uv run just test`. They need no database server and no environment.
4. Start the stack in Docker: `uv run just up`. It creates the network and the Postgres container once, builds the image from the working tree, runs the migrations and serves on port 5002. The API docs are at `http://localhost:5002/docs`. Log in with the admin token from your `.env`.
5. Or run the code as Vercel runs it, without Docker: `uv run just serve`. Migrate first with `uv run just local alembic upgrade head`.
6. Load real data: `uv run just local seed` clones the private seed repository, if you have access, and loads it. Or `uv run just local import-xlsx` imports the two real workbooks from `tests/data`.
7. Read the log with `uv run just logs`, open psql with `uv run just psql`, stop with `uv run just down`. The data stays in the named volume.

# Without Docker

WSL and some laptops have no Docker. A real Postgres runs from the `pgserver` wheel on Python 3.12 (the wheels stop there): start it once, point `DB_URL` at its socket, and run `uv run just serve`. `TEST_DB_URL` runs the whole suite on it.

# The two URL forms

`DB_URL` names the same database twice. Inside a container on the `gnl-net` network the host is `gnl-postgres`; on the laptop it is `localhost`. The recipes pass the right form; typing the commands by hand is where this goes wrong.

# Daily loop

Change code, `uv run just up` again to rebuild, `uv run just fmt` before committing, `uv run just lint` and `uv run just typecheck` as CI runs them.
