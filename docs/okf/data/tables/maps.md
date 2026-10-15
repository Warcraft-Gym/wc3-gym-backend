---
type: Data Model
title: maps
description: "One map: its name, its short name and the public URL of its picture."
resource: ../../../../app/models/map.py
tags: [maps, data]
generated: { by: claude-code/claude-opus-5-5, at: 2026-10-15T09:00:00Z }
verified: { by: process:test_okf, at: 2026-09-14T17:40:50Z }
sources:
  - id: model
    resource: ../../../../app/models/map.py
    title: Map
  - id: maps
    resource: ../../../../app/services/maps.py
    title: MapService
  - id: ladder-maps
    resource: ../../../../app/services/ladder_maps.py
    title: The ladder map import writes image from the map publisher
---

# Schema

| Column | Type | Null | Meaning |
|---|---|---|---|
| `id` | INTEGER | no | Primary key. |
| `name` | VARCHAR | yes | The full name. |
| `shortname` | VARCHAR | yes | The short name. Unique, case-insensitive, after trimming; the import matches a map on it. |
| `modes` | VARCHAR | yes | The modes the map is played as, comma-joined in the order `1v1`, `2v2`, `3v3`, `4v4`, `5v5`, `6v6`, `8v8`, `ffa`, `custom`; each once. The ladder import adds the mode of the ladder it reads; an admin edits the rest. A cup offers the maps of its own mode first. Null names none yet. |
| `image` | VARCHAR | yes | The public URL of the picture: the blob an admin uploaded, else the URL the ladder import found. An upload wins over an import. |

# Keys and joins

Primary key `id`. Unique expression index on `lower(trim(shortname))`. Pointed at by [map_season](map_season.md), [event_round](event_round.md), [matches](matches.md) (`fixed_map_id`), [series_game](series_game.md), [series_veto_step](series_veto_step.md).

# Rules

No bytes column. `POST /maps/custom` lets an organizer name a custom game's map: it answers the map whose name or short name is that name, case and spaces aside, or adds one marked `custom`, its short name kept apart from every other map's; an admin adds its picture. See [pictures and replays](../../concepts/pictures-and-replays.md).
