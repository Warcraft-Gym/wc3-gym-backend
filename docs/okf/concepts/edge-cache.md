---
type: Domain Concept
title: Edge cache
description: Every open read the edge caches uses one of three timer classes, live, running or settled, and an event read picks running or settled from the event's phase; nothing is purged.
resource: ../../../app/api/deps.py
tags: [api, deploy]
generated: { by: claude-code/claude-opus-5-5, at: 2026-09-26T12:00:00Z }
sources:
  - id: deps
    resource: ../../../app/api/deps.py
    title: edge_cache, phase_edge_cache and event_edge_cache
  - id: tests
    resource: ../../../tests/test_edge_cache.py
    title: The header each cached route answers
---

# Edge cache

The Vercel edge keeps one copy of an open read and serves it to every caller until its timer runs out. The timer is the only way a copy leaves the edge. No write purges, tags or revises an entry. A reader sees a change at most `s-maxage` plus `stale-while-revalidate` seconds late, unless the reader sends a bearer, which skips the edge.

## The three classes

`edge_cache(response, cls)` in `app/api/deps.py` writes the header of one class and `Access-Control-Allow-Origin: *` beside it (see [the pitfall](../pitfalls/edge-cache-cors.md)).

| Class | `Cache-Control` | Use it for |
|---|---|---|
| live | `public, s-maxage=15` | a board a page polls: the open KOTH night |
| running | `public, s-maxage=120, stale-while-revalidate=600` | an answer a reported result or an edit changes soon: a running event, a player's read and history, the home series strip, league teams |
| settled | `public, s-maxage=3600, stale-while-revalidate=86400` | an answer that changes only when an admin corrects it: a finished event, a closed KOTH night, career stats, the reference lists |

## The phase rule

An event read is settled once the event's phase is `finished`, and running in every other phase. `phase_edge_cache(response, phase)` takes a phase the answer already carries. `event_edge_cache(response, event_id)` is for a route whose answer carries no phase: it reads the event and its phase once. A missing event is running. The KOTH board is live for an open night and settled once `closed` is true on its answer.

## The anonymous-only rule

A route caches only an answer that is the same for every caller. A route whose answer changes with the caller sets the header only when the caller sends no bearer, because the edge serves a cached copy only to a request with no Authorization header. An admin's requests always carry the bearer, so an admin reads past the cache. An error answer carries no cache header, because the error handlers build a fresh response.

## Cached routes

Each route's deprecated aliases carry the same header.

| Route | Class |
|---|---|
| `GET /koth/board`, `GET /koth/nights/{night_id}/board` | live while the night is open, settled once it is closed |
| `GET /home/series` | running |
| `GET /users/{key}`, for an anonymous caller only | running |
| `GET /users/{user_id}/ladder`, `GET /users/{user_id}/history` | running |
| `GET /leagues/{league_id}/teams`, its `basic` twin, `GET /leagues/{league_id}/teams/{team_id}` | running |
| `GET /events/{event_id}`, for an anonymous caller only | by the event's phase |
| `GET /events/{event_id}/entrants`, `GET /events/{event_id}/achievements` | by the event's phase |
| `GET /events/{event_id}/series`, `GET /events/{event_id}/stages/{stage_id}/series`, `GET /events/{event_id}/stages/{stage_id}/standings` | by the event's phase |
| `GET /events/{event_id}/teams`, its `basic` twin, `GET /events/{event_id}/teams/{team_id}` | by the event's phase |
| `GET /events/{event_id}/ladder`, `GET /events/{event_id}/ladder/players` | by the event's phase |
| `GET /stats/career`, `GET /stats/career/{user_id}` | settled |
| `GET /events`, for an anonymous caller only | settled |
| `GET /leagues`, `GET /maps`, `GET /config/w3c`, `GET /config/settings/{key}` | settled |

`GET /config/w3c` sets the header only when w3champions answered, so an outage answer is never cached. Every other read is uncached. A route added here is cached once the frontend's `EDGE_CACHED` pattern lists it too. `tests/test_edge_cache.py` and the route tests pin every row.
