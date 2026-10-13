---
type: Data Model
title: cup_settings
description: A cup's own settings beside its event row; its choice to split its players into divisions, and the points each place of a round pays.
resource: ../../../../app/models/cup_settings.py
tags: [events, data]
generated: { by: claude-code/claude-opus-5-5, at: 2026-10-13T16:00:00Z }
sources:
  - id: model
    resource: ../../../../app/models/cup_settings.py
    title: CupSettings
  - id: rules
    resource: ../../../../app/services/cup_divisions.py
    title: A cup's division rules
---

# Schema

| Column | Type | Null | Meaning |
|---|---|---|---|
| `event_id` | INTEGER | no | Primary key. The cup. |
| `uses_divisions` | BOOLEAN | no | On: the cup splits its players into divisions, cut on its run page. Defaults to false. |
| `points_by_place` | VARCHAR(200) | yes | A cup played over rounds: what each place of a round pays, best first, as `10,8,6,5,4,3,2,1`. Null pays that default; a place past the list pays 0. |

# Keys and joins

Primary key `event_id`, a foreign key to [event](event.md), `ON DELETE CASCADE`.

# Rules

- `POST /events` writes the row of every new cup from its `uses_divisions` field. The full event read answers it as `uses_divisions`; it reads null on any other kind and on a list read.
- With `uses_divisions` off, every division write of the cup is refused, and the cup plays one field. `PUT /events/{id}` with `uses_divisions` false takes the cup's divisions back, and is refused once the cup is drawn.
- `POST /events` for a cup with `legs` writes `points_by_place` from its list of the same name; a negative value is refused. `GET /events/{id}/overall` answers the table the cup pays.
- The row exists so a cup-only choice needs no column on [event](event.md), which GNL and KOTH read. See [events module](../../concepts/events-module.md#entrants-seeds-divisions).
