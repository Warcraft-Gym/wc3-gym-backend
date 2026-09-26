---
type: API Area
title: API overview
description: Twenty-one route modules under one FastAPI app, one error envelope, paging with a total header, a search language, and OpenAPI at /docs.
resource: ../../../app/api/main.py
tags: [api]
generated: { by: claude-code/claude-opus-5-5, at: 2026-09-26T10:02:14Z }
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

List routes take `limit` (1 to 500) and `offset`. The default page is 500, except on the routes whose set a season's structure bounds, which page smaller (`GET /events/{event_id}/teams` and its `basic` twin and `GET /fantasy/bets` at 50; `GET /events/{event_id}/fantasy/teams`, `POST /users/search`, `POST /matches/search`, `GET /maps`, `GET /draft-series/match/{match_id}` and `GET /player-series` at 100). Seven routes carry the total row count in `X-Total-Count`, which CORS exposes. Three routes take `sort` and `order`; a name outside their table answers 422. Without `sort` a route keeps its default order, pinned per route by `tests/test_paging.py`. The career list derives its rating, filters, sorts and pages in SQL, then sends only the selected page. List answers are reduced: every key stays and nested collections answer `[]`; the single-row routes keep the full graph. A row of a series list (the season, round, global and player series reads, and the stage series read) carries no W3Champions stats, so it names the rating of each side on the race it plays in `player1_mmr` and `player2_mmr`. On a running event that is the `w3cstats` rating: the newest row of the live window (the current W3Champions season and the one before it) that carries a rating above 0 on that race, null otherwise. On a finished event it is the MMR of the time, `mmr_at` at the series time (see [Ladder and achievements](../concepts/ladder-and-achievements.md)). On every other series payload the two keys read null. Three reads tell finished events from running ones; the running rows are rated in two statements, three while the W3Champions season setting is unset, and each finished event in the list costs one statement; none is spent per row. The reads that carry players (the user list and search, the signups, the team rosters and captains, the fantasy team lists and `GET /series/{series_id}`) load the live window's rows in `w3c_stats` and nothing older; `GET /users/{key}` and the single fantasy team read carry every stored season. Those players carry the ladder summary, `race_mmrs` and `main_race` (see [w3cstats](../data/tables/w3cstats.md)); a roster of an event that is over also carries `mmr_entered`.

# The search language

`POST /<area>/search` takes a `query` such as `season_id == 3 and name ilike smith`, parsed by `app/core/query.py`. Use a service's `find_by_*` method for a value the caller supplies; keep the language for a query a client wrote.

`POST /events/search` returns the same `EventPublic` shape and applies the same draft visibility as `GET /events`.

# CORS and caching

CORS allows every origin, because clients send bearer tokens and never cookies. A route that sets `Cache-Control: public` must write `Access-Control-Allow-Origin: *` itself, next to it. See [the pitfall](../pitfalls/edge-cache-cors.md). A route whose answer belongs to one caller sets `Cache-Control: private` and `Vary: Authorization` instead, so no shared cache stores a copy and the browser's own copy is keyed on the bearer that names the caller.

`edge_cache(response, cls)` in `app/api/deps.py` writes both headers for one of three timer classes: live, running or settled. An event read picks running or settled from the event's phase. Only a route with no guard whose answer is the same for every caller uses it. [Edge cache](../concepts/edge-cache.md) states the classes, the phase rule and every cached route.

The edge serves a cached copy only to a request with no Authorization header. The frontend sends a route without its bearer only when its `EDGE_CACHED` pattern lists the route, and an admin's requests always carry the bearer, so an admin reads past the cache. A route added here is cached once the frontend pattern lists it too.

## What a read costs

A cache hit is served by the Vercel edge: the function does not run and the database is not read. A miss runs the route once and fills the entry for that region. So the database cost of an open read is the rows one miss reads times the number of misses, and the number of page views does not enter it. A route with no `edge_cache` has a miss on every call.

A write does not clear the edge. A reader sees a change up to `s-maxage` plus `stale-while-revalidate` seconds late, unless the reader sends a bearer, which skips the edge. Pick the [class](../concepts/edge-cache.md#the-three-classes) by how often the answer changes and how late a reader may see it.

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
