---
type: Data Model
title: cup_occurrence
description: One cup made from a recurring rule, on one of the rule's days.
resource: ../../../../app/models/cup_recurrence.py
tags: [events, data]
generated: { by: claude-code/claude-opus-5-5, at: 2026-10-15T21:00:00Z }
sources:
  - id: model
    resource: ../../../../app/models/cup_recurrence.py
    title: CupOccurrence
  - id: rules
    resource: ../../../../app/services/cup_recurrence.py
    title: Recurring cups
---

# Schema

| Column | Type | Null | Meaning |
|---|---|---|---|
| `event_id` | INTEGER | no | Primary key. The cup. |
| `recurrence_id` | INTEGER | no | The rule it was made from. |
| `occurs_on` | DATE | no | The rule's day the cup is played on, in the rule's zone. |

# Keys and joins

Primary key `event_id`, a foreign key to [event](event.md), `ON DELETE CASCADE`. Foreign key `recurrence_id` to [cup_recurrence](cup_recurrence.md), `ON DELETE CASCADE`, indexed. Unique (`recurrence_id`, `occurs_on`), so a day holds one cup of a rule.

# Rules

- `POST /cup-recurrences/{id}/occurrences` with `on` makes the cup of a coming day the rule names, for a runner of the latest cup: a copy of the latest cup with its sign-up rules, stages, map pool, divisions choice, custom game choice, points table and organizers, its start on that day at the rule's time, and on a cup over rounds every round moved by the same days. A day that has passed or that the rule does not name answers 400, and a day with its cup answers 409.
- The full event read of a cup made from a rule answers it as `cup_recurrence`, its id and name.
