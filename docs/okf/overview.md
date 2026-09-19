---
type: Repository
title: wc3-gym-backend
description: The FastAPI backend of the Warcraft Gym league app, on Vercel with a Supabase Postgres, serving the web app, the WordPress site, the Discord adapter and Nightbot.
resource: https://github.com/Warcraft-Gym/wc3-gym-backend
tags: [data, api, deploy]
generated: { by: claude-code/claude-fable-5-1, at: 2026-09-19T10:00:00Z }
sources:
  - id: readme
    resource: ../../README.md
    title: README
  - id: pyproject
    resource: ../../pyproject.toml
    title: Project metadata
---

# What it is

The one backend of the Gym Newbie League (GNL) and the other Warcraft Gym events: players, teams, seasons, series, results, the fantasy game, King of the Hill nights, the W3Champions ladder mirror, and the Discord commands and cards. It is a FastAPI application on SQLModel and Postgres, deployed as one Vercel function, with Clerk sessions for members and a shared admin token for the admin UI and scripts.

# Where it runs

| Target | What |
|---|---|
| production | Vercel project `wc3-gym-backend`, built from `main`, database on the production Supabase project through the transaction pooler |
| staging | the `staging` branch, force-pushed to the merged commit on every push to `main`; a preview at a fixed alias against the shared staging database |
| previews | every pull request; a branch that adds a migration gets its own copy of the staging database |
| local | `uv run just up` (Docker) or `uv run just serve` (the Vercel entry point from the working tree) |

The Azure VM and Docker Compose paragraphs in the README describe the older self-hosted line; this repository no longer supports it.

# Layout

```
api/        the Vercel entry point and the preview-database choice
app/
  main.py   create_app: engine, routers, error handlers
  api/      deps.py (guards, services), routes/ (one module per area)
  core/     engine, query language, exceptions, security, the pure rules
  services/ one service per entity; derived.py computes scores at read time
  models/   SQLModel table classes and their Create, Update and Public shapes
migrations/ Alembic
tests/      pytest, on a migrated SQLite file
just/       one module per place the backend runs: local, azure, vercel
docs/       PICTURES.md, PREVIEW-DATABASES.md, and this bundle
```

# Start here

1. [Vocabulary](concepts/vocabulary.md), then [GNL season](concepts/gnl-season.md) and [events module](concepts/events-module.md).
2. [Layering](conventions/layering.md), [model families](data/model-families.md), [API overview](api/overview.md), [authentication](api/auth.md).
3. [Run locally](runbooks/run-locally.md), [testing](conventions/testing.md).
4. Before a change: [git and pull requests](conventions/git-and-pull-requests.md), the [decisions](decisions/index.md) and the [pitfalls](pitfalls/index.md).

# Contributing

The maintainers build with AI coding agents and review every pull request before it merges. A contributor who reads this bundle and the code, works on a fork or a branch, and opens a small pull request is the expected path in.
