---
type: API Area
title: API overview
description: Twenty-one route modules under one FastAPI app, one error envelope, paging with a total header, a search language, and OpenAPI at /docs.
resource: ../../../app/api/main.py
tags: [api]
generated: { by: claude-code/claude-opus-5-5, at: 2026-09-24T17:00:00Z }
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
| `users.py` | `/users` | players, a member's own battle tags, the admin tag move and merge, bans, blocks, W3Champions sync, history, the meetings of two players |
| `teams.py` | `/leagues/{league_id}/teams`, `/events/{event_id}/teams`, `/teams/{team_id}/image` | league-owned teams, event rosters, captains, availability grid, logos; the unscoped logo read is deprecated |
| `seasons.py` | `/events/{event_id}`, `/achievements` | GNL maps, rounds, signups, ladder reads and badges |
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

The OpenAPI version is `1.1.0`. GNL creation and management live on the event routes; no `/seasons` route exists.

# The error envelope

Every error answers `{"error": "<text>"}` with the status: 404 `NotFoundError`, 400 `BadRequestError`, 502 `ExternalServiceError`, 409 integrity conflicts ("Row already exists" or "Row is still referenced") and the one rule conflict a route states in a sentence, 422 validation with the field names in the text, 500 with the fixed text "Internal Server Error" and the detail in the log. The router's own 404 and 405 carry the envelope too. A few public routes add a second key, `message`, with human text beside an `error` code. `tests/test_error_envelope.py` locks it. FastAPI's stock `{"detail": ...}` never reaches a client.

# Paging and sorting

List routes take `limit` (1 to 500) and `offset`. The default page is 500, except on the routes whose set a season's structure bounds, which page smaller (`GET /events/{event_id}/teams` and its `basic` twin and `GET /fantasy/bets` at 50; `GET /events/{event_id}/fantasy/teams`, `POST /users/search`, `POST /matches/search`, `GET /maps`, `GET /draft-series/match/{match_id}` and `GET /player-series` at 100). Seven routes carry the total row count in `X-Total-Count`, which CORS exposes. Three routes take `sort` and `order`; a name outside their table answers 422. Without `sort` a route keeps its default order, pinned per route by `tests/test_paging.py`. List answers are reduced: every key stays and nested collections answer `[]`; the single-row routes keep the full graph. A row of a series list (the season, round, global and player series reads, and the stage series read) carries no W3Champions stats, so it names the rating of each side on the race it plays in `player1_mmr` and `player2_mmr`: the newest stored W3Champions season that carries a rating above 0 on that race, three seasons back and no further, null otherwise; on every other series payload the two keys read null. A whole list is rated in two statements, three while the W3Champions season setting is unset, and none per row. The fantasy team lists (the global list, the search and the per-event list) carry the same window on their drafted players: each player's `w3c_stats` holds the seasons within three of the W3Champions season the app rates against, and nothing older. The single fantasy team read carries every stored season.

# The search language

`POST /<area>/search` takes a `query` such as `season_id == 3 and name ilike smith`, parsed by `app/core/query.py`. Use a service's `find_by_*` method for a value the caller supplies; keep the language for a query a client wrote.

`POST /events/search` returns the same `EventPublic` shape and applies the same draft visibility as `GET /events`.

# CORS and caching

CORS allows every origin, because clients send bearer tokens and never cookies. A route that sets `Cache-Control: public` must write `Access-Control-Allow-Origin: *` itself, next to it. See [the pitfall](../pitfalls/edge-cache-cors.md). A route whose answer belongs to one caller sets `Cache-Control: private` and `Vary: Authorization` instead, so no shared cache stores a copy and the browser's own copy is keyed on the bearer that names the caller.

`edge_cache(response, s_maxage, swr)` in `app/api/deps.py` writes both headers: `Cache-Control: public, s-maxage=<s_maxage>`, with `stale-while-revalidate=<swr>` when given, and `Access-Control-Allow-Origin: *`. Only a route with no guard whose answer is the same for every caller uses it. `event_edge_cache(response, event_id)` beside it picks the timing by the event's phase: a finished event changes only when an admin corrects it. An error answer carries neither header, because the error handlers build a fresh response. These routes use it, and their deprecated aliases with them:

| Route | s-maxage | stale-while-revalidate |
|---|---|---|
| `GET /koth/board`, `GET /koth/nights/{night_id}/board` | 15 | none |
| `GET /home/series` | 120 | none |
| `GET /events/{event_id}/ladder` | 3600 | none |
| `GET /events/{event_id}/ladder/players`, `GET /users/{user_id}/ladder` | 900 | 3600 |
| `GET /stats/career` | 3600 | 3600 |
| `GET /leagues`, `GET /maps`, `GET /config/w3c`, `GET /config/settings/{key}` | 300 | 3600 |
| `GET /users/{user_id}/history` | 120 | 600 |
| `GET /events/{event_id}/teams`, its `basic` twin, `GET /events/{event_id}/teams/{team_id}`, `GET /events/{event_id}/series` | 120, or 3600 once the event is finished | 600, or 86400 once the event is finished |
| `GET /leagues/{league_id}/teams`, its `basic` twin, `GET /leagues/{league_id}/teams/{team_id}` | 120 | 600 |

The edge serves a cached copy only to a request with no Authorization header. The frontend sends a route without its bearer only when its `EDGE_CACHED` pattern lists the route, and an admin's requests always carry the bearer, so an admin reads past the cache. A route added here is cached once the frontend pattern lists it too. `tests/test_edge_cache.py` pins every row.

## What a read costs

A cache hit is served by the Vercel edge: the function does not run and the database is not read. A miss runs the route once and fills the entry for that region. So the database cost of an open read is the rows one miss reads times the number of misses, and the number of page views does not enter it. A route with no `edge_cache` has a miss on every call.

A write does not clear the edge. A reader sees a change up to `s-maxage` plus `stale-while-revalidate` seconds late, unless the reader sends a bearer, which skips the edge. Pick `s-maxage` by how often the answer changes and how late a reader may see it:

| Answer | `s-maxage` |
|---|---|
| a live board during a night | seconds |
| a running event: fixtures, results, teams | minutes |
| a finished event, which changes only when an admin corrects it | an hour or more, with a long `stale-while-revalidate` |
| the list of leagues, maps, settings | minutes, with an hour of `stale-while-revalidate` |

## Rules for a route a consumer reads

- An open GET that answers every caller the same sets `edge_cache`. A route left without it says why in its docstring.
- A route returns the rows its readers use. When a page needs one team's or one player's rows, add a route scoped to that team or player instead of having the page filter an event-wide list.
- `X-DB-Rows` on the response, the egress ledger and `tests/test_query_budget.py` give the rows per call. A pull request that adds or widens a consumer's read states the rows per call and the cache time. See [Consumers of the API](consumers.md) for the consumer's side.

`GET /koth/board` and `GET /koth/nights/{night_id}/board` Both answer `KothBoard`, keyed `night_id` with a `closed` flag, and every write of a live night answers the same shape, so the run page needs no second read. See [KOTH night](../concepts/koth.md).

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
