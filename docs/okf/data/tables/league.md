---
type: Data Model
title: league
description: One thing that repeats, such as the GNL or KOTH; each run of it is an event.
resource: ../../../../app/models/league.py
tags: [events, data]
generated: { by: claude-code/claude-fable-5-1, at: 2026-09-14T15:15:00Z }
verified: { by: process:test_okf, at: 2026-09-14T17:40:50Z }
sources:
  - id: model
    resource: ../../../../app/models/league.py
    title: League
  - id: events
    resource: ../../../../app/services/events.py
    title: EventService.add_league and update_league
---

# Schema

| Column | Type | Null | Meaning |
|---|---|---|---|
| `id` | INTEGER | no | Primary key. |
| `name` | VARCHAR | no | The full name. Unique. |
| `short_name` | VARCHAR | yes | The short form every event payload carries as `league_short_name`. |
| `page_url` | VARCHAR | yes | The league's landing or rules page, shown as one "Page" link. |
| `rules_url` | VARCHAR | yes | The rules the league plays by. Set by the admin form; answered on the league payload; no service reads it. |
| `stream_url` | VARCHAR | yes | Where the league's games are streamed. Set by the admin form; answered on the league payload; no service reads it. |
| `kind` | VARCHAR | no | `gnl`, `koth` or `custom`. The app finds the GNL and the KOTH league by this value; a league an admin makes is `custom`. |
| `entrant_kind` | VARCHAR | no | Who enters its events: `solo`, `team` or `drafted_teams`. Copied onto each new event. |
| `created_at` | TIMESTAMP | no | When the row was written. Set by the app. No route reads it. |

# Keys and joins

Primary key `id`. Unique constraint on `name`. Pointed at by [event](event.md) `league_id`.

# Rules

A league carries no defaults for its events beyond `entrant_kind`. See [events module](../../concepts/events-module.md) and [vocabulary](../../concepts/vocabulary.md).
