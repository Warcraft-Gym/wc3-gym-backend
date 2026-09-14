---
type: Convention
title: Layering
description: Routes call services, services own their transactions, models hold the schema and the shapes, and pure rules live in app/core.
tags: [architecture, fastapi, sqlmodel]
generated: { by: claude-code/claude-fable-5-1, at: 2026-09-14T10:00:00Z }
sources:
  - id: main
    resource: ../../../app/main.py
    title: The application factory
  - id: deps
    resource: ../../../app/api/deps.py
    title: The guards and the service graph
  - id: db
    resource: ../../../app/core/db.py
    title: The engine and the session factory
---

# The three layers

| Layer | Where | What it does |
|---|---|---|
| Routes | `app/api/routes/*.py` | One module per API area. A route validates the request through a typed body model, picks the guard, calls one service method, and returns a Public model. No SQL here. |
| Services | `app/services/*.py` | One service per entity, plus a few that compute across entities. A service opens its own session with `Session.begin()`, one transaction per call, and never commits by hand. To share a transaction, pass the session down. |
| Models | `app/models/*.py` | SQLModel table classes and their request and response shapes. See [model families](../data/model-families.md). |

`app/core/` holds what is neither a route nor a service: the engine, the query language of the search routes, the exceptions, the security helpers, and the pure rules (scoring, career rating, fantasy, ladder, achievements, brackets, divisions). A pure rule reads no database. Where a rule has a SQL face and a Python face, a test pins the two to each other.

# The application factory

`create_app` in `app/main.py` builds the engine and registers the routers. Importing any app module opens no connection and creates no table; the tables come from `alembic upgrade head` before the server starts. The server calls the factory: `uvicorn --factory app.main:create_app`. Vercel imports `api/index.py`, which calls the same factory.

`create_app` reads the process environment only. No `.env` file is read below the entry points; `api/index.py` and the `just` modules load one. The tests therefore never see a laptop's `.env`.

# The service graph

`app/api/deps.py` builds one instance of every service for the process and exposes each as an `Annotated` dependency, `SeasonServiceDep` and so on. Services are stateless besides their references to each other. Building them touches no database.

The same module holds the guards: `require_login`, `require_member`, `require_captain`, `require_admin`, `optional_login`. See [authentication](../api/auth.md).

# Sync, not async

Route handlers and services are plain `def`. FastAPI runs them in a thread pool. The SQLAlchemy layer blocks, so `async def` around it would be worse, not better.

# Errors

A service raises `NotFoundError`, `BadRequestError`, `ExternalServiceError` or `ApiError`. `create_app` turns each into the one error envelope every client reads. See [the API overview](../api/overview.md). Never add a handler that leaks `str(e)` from an unknown exception.

# Derived, not stored

Points, standings, career totals and fantasy scores are computed at read time from the map scores. No column holds a rollup, and there is no recalculate button. See [derived scores](../concepts/derived-scores.md) and [the decision](../decisions/derived-not-stored.md).
