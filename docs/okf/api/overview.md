---
type: API Area
title: API overview
description: Seventeen route modules under one FastAPI app, one error envelope, paging with a total header, a search language, and OpenAPI at /docs.
resource: ../../../app/api/main.py
tags: [api, fastapi, routes]
generated: { by: claude-code/claude-fable-5-1, at: 2026-09-14T10:00:00Z }
sources:
  - id: router
    resource: ../../../app/api/main.py
    title: The routers, in order
  - id: main
    resource: ../../../app/main.py
    title: The error handlers
  - id: query
    resource: ../../../app/core/query.py
    title: The search language
  - id: readme
    resource: ../../../README.md
    title: List routes and paging
---

# Route modules

| Module | Prefix | Area |
|---|---|---|
| `login.py` | `/login`, `/me` | the admin token login and the session answer |
| `users.py` | `/users` | players, bans, blocks, W3Champions sync, history |
| `teams.py` | `/teams` | teams, rosters, captains, availability grid, logos |
| `seasons.py` | `/seasons`, `/achievements` | seasons, maps, rounds, signups, ladder reads, badges |
| `leagues.py` | `/leagues` | leagues |
| `events.py` | `/events`, `/me/events` | events, entrants, divisions, stages, standings |
| `matches.py` | `/matches` | fixtures |
| `series.py` | `/series`, `/casts` | series, result kind, places, sides, casts |
| `draft_series.py` | `/draft-series` | a captain's proposed series |
| `public.py` | `/signup`, `/player-series`, `/player-availability`, `/player-blocks`, `/player-history`, `/user-info`, `/fantasy-team`, `/fantasy-bet` | a member's own flows |
| `maps.py` | `/maps` | maps and the ladder import |
| `fantasy.py` | `/fantasy` | admin fantasy management and the breakdown |
| `koth.py`, `koth_nights.py` | `/koth` | nights and the old KOTH payloads |
| `config.py` | `/config` | settings, admins, role bindings, role sync |
| `stats.py` | `/stats/career` | career stats |
| `import_export.py` | `/import`, `/export`, `/fantasy/import` | workbooks |
| `jobs.py` | `/jobs` | the scheduled jobs |
| `discord.py` | `/discord/interactions` | the forwarded Discord interactions |
| `health.py` | `/health` | liveness |

Swagger UI is at `/docs` and the OpenAPI document at `/openapi.json`. FastAPI includes routers lazily, so enumerate routes from `app.openapi()["paths"]`, not from `app.routes`.

# The error envelope

Every error answers `{"error": "<text>"}` with the status: 404 `NotFoundError`, 400 `BadRequestError`, 502 `ExternalServiceError`, 409 integrity conflicts ("Row already exists" or "Row is still referenced"), 422 validation with the field names in the text, 500 with the fixed text "Internal Server Error" and the detail in the log. The router's own 404 and 405 carry the envelope too. A few public routes add a second key, `message`, with human text beside an `error` code. `tests/test_error_envelope.py` locks it. FastAPI's stock `{"detail": ...}` never reaches a client.

# Paging and sorting

List routes take `limit` (1 to 500, default 500) and `offset`. Seven routes carry the total row count in `X-Total-Count`, which CORS exposes. Three routes take `sort` and `order`; a name outside their table answers 422. Without `sort` a route keeps its default order, pinned per route by `tests/test_paging.py`. List answers are reduced: every key stays and nested collections answer `[]`; the single-row routes keep the full graph.

# The search language

`POST /<area>/search` takes a `query` such as `season_id == 3 and name ilike smith`, parsed by `app/core/query.py`. Use a service's `find_by_*` method for a value the caller supplies; keep the language for a query a client wrote.

# CORS and caching

CORS allows every origin, because clients send bearer tokens and never cookies. A route that sets `Cache-Control: public` must write `Access-Control-Allow-Origin: *` itself, next to it. See [the pitfall](../pitfalls/edge-cache-cors.md).
