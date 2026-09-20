---
type: API Area
title: API overview
description: Twenty-one route modules under one FastAPI app, one error envelope, paging with a total header, a search language, and OpenAPI at /docs.
resource: ../../../app/api/main.py
tags: [api]
generated: { by: claude-code/claude-fable-5-1, at: 2026-09-20T21:00:00Z }
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
| `users.py` | `/users` | players, bans, blocks, W3Champions sync, history, the meetings of two players |
| `teams.py` | `/leagues/{league_id}/teams`, `/events/{event_id}/teams`, `/teams` | league-owned teams, event rosters, captains, availability grid, logos; deprecated unscoped aliases |
| `seasons.py` | `/events/{event_id}`, `/seasons`, `/achievements` | GNL maps, rounds, signups, ladder reads and badges; deprecated season aliases |
| `leagues.py` | `/leagues` | leagues |
| `events.py` | `/events`, `/me/events` | event CRUD and search, entrants, divisions, stages, standings |
| `matches.py` | `/matches` | fixtures |
| `series.py` | `/series`, `/events/{event_id}/series`, `/casts` | series, event series searches, result kind, places, sides, casts |
| `draft_series.py` | `/draft-series`, `/matches/{match_id}/draft-board` | a captain's proposed series, the Ready, seen and MMR state of one fixture's draft, and every figure its draft board draws |
| `home.py` | `/home/series` | the home page's cross-event series lists |
| `public.py` | `/signup`, `/player-series`, `/player-availability`, `/player-blocks`, `/player-history`, `/user-info`, `/fantasy-team`, `/fantasy-bet`, `/events/{event_id}/rounds` | a member's own flows, and a captain's read of the hours a pair shares in a round |
| `maps.py` | `/maps` | maps and the ladder import |
| `fantasy.py` | `/fantasy`, `/events/{event_id}/fantasy` | admin fantasy management and event-scoped reads, tiers and breakdowns |
| `koth.py`, `koth_nights.py` | `/koth` | nights, the live night an admin runs, the board, and the old KOTH payloads |
| `config.py` | `/config` | settings, admins, role bindings, role sync |
| `stats.py` | `/stats/career` | career stats |
| `import_export.py` | `/import`, `/export`, `/fantasy/import` | workbooks |
| `jobs.py` | `/jobs` | the scheduled jobs |
| `discord.py` | `/discord/interactions` | the forwarded Discord interactions |
| `health.py` | `/health` | liveness |

Swagger UI is at `/docs` and the OpenAPI document at `/openapi.json`. FastAPI includes routers lazily, so enumerate routes from `app.openapi()["paths"]`, not from `app.routes`.

The OpenAPI version is `1.1.0`. This version adds GNL creation and management to the event routes. Every `/seasons` operation is deprecated in OpenAPI and remains available during the consumer migration.

# The error envelope

Every error answers `{"error": "<text>"}` with the status: 404 `NotFoundError`, 400 `BadRequestError`, 502 `ExternalServiceError`, 409 integrity conflicts ("Row already exists" or "Row is still referenced") and the one rule conflict a route states in a sentence, 422 validation with the field names in the text, 500 with the fixed text "Internal Server Error" and the detail in the log. The router's own 404 and 405 carry the envelope too. A few public routes add a second key, `message`, with human text beside an `error` code. `tests/test_error_envelope.py` locks it. FastAPI's stock `{"detail": ...}` never reaches a client.

# Paging and sorting

List routes take `limit` (1 to 500, default 500) and `offset`. Seven routes carry the total row count in `X-Total-Count`, which CORS exposes. Three routes take `sort` and `order`; a name outside their table answers 422. Without `sort` a route keeps its default order, pinned per route by `tests/test_paging.py`. List answers are reduced: every key stays and nested collections answer `[]`; the single-row routes keep the full graph. A row of a series list (the season, round, global and player series reads, and the stage series read) carries no W3Champions stats, so it names the rating of each side on the race it plays in `player1_mmr` and `player2_mmr`: the newest stored W3Champions season that carries a rating above 0 on that race, three seasons back and no further, null otherwise; on every other series payload the two keys read null. A whole list is rated in two statements, three while the W3Champions season setting is unset, and none per row.

# The search language

`POST /<area>/search` takes a `query` such as `season_id == 3 and name ilike smith`, parsed by `app/core/query.py`. Use a service's `find_by_*` method for a value the caller supplies; keep the language for a query a client wrote.

`POST /events/search` returns the same `EventPublic` shape and applies the same draft visibility as `GET /events`.

# CORS and caching

CORS allows every origin, because clients send bearer tokens and never cookies. A route that sets `Cache-Control: public` must write `Access-Control-Allow-Origin: *` itself, next to it. See [the pitfall](../pitfalls/edge-cache-cors.md). A route whose answer belongs to one caller sets `Cache-Control: private` and `Vary: Authorization` instead, so no shared cache stores a copy and the browser's own copy is keyed on the bearer that names the caller.

`GET /koth/board` and `GET /koth/nights/{night_id}/board` are the pair that sets `public, s-maxage=15`. Both answer `KothBoard`, keyed `night_id` with a `closed` flag, and every write of a live night answers the same shape, so the run page needs no second read. See [KOTH night](../concepts/koth.md).

# Examples

A paged list, with the total in the header:

```http
GET /teams?limit=2&offset=0

200 OK
X-Total-Count: 6

[ { "id": 1, "name": "Team A", ... }, { "id": 2, "name": "Team B", ... } ]
```

An offset past the end answers `200 []`. Every error carries the envelope and nothing else:

```http
GET /no-such-path          -> 404 {"error": "Not Found"}
DELETE /health             -> 405 {"error": "Method Not Allowed"}
POST /users/search {"query": "name ==="}   -> 400 {"error": "<what the parser refused>"}
```

A bug answers `500 {"error": "Internal Server Error"}` with the detail in the log, never in the body.
