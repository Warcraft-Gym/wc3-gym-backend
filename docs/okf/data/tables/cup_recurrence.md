---
type: Data Model
title: cup_recurrence
description: The rule a cup repeats on, a weekday every week or the nth of the month at a local start time, from which a runner makes each next cup.
resource: ../../../../app/models/cup_recurrence.py
tags: [events, data]
generated: { by: claude-code/claude-opus-5-5, at: 2026-10-15T11:30:00Z }
sources:
  - id: model
    resource: ../../../../app/models/cup_recurrence.py
    title: CupRecurrence
  - id: rules
    resource: ../../../../app/services/cup_recurrence.py
    title: Recurring cups
---

# Schema

| Column | Type | Null | Meaning |
|---|---|---|---|
| `id` | INTEGER | no | Primary key. |
| `name` | VARCHAR(80) | no | The rule's name; each cup made from it is named after it and its day, such as `Friday Cup 11 Jan 2030`. |
| `weekday` | INTEGER | no | The day of the week the cup is played, 0 Monday to 6 Sunday. |
| `nth` | INTEGER | yes | Null plays every week; 1 to 4 the nth such weekday of the month; -1 the last. |
| `start_time` | VARCHAR(5) | no | The local start time, `HH:MM`, in `zone`. |
| `zone` | VARCHAR(64) | no | The IANA time zone the start time is read in. |
| `starts_on` | DATE | no | The day of the cup the rule was made from, its first occurrence; the rule names no day before it. |
| `ends_on` | DATE | yes | The rule's last day; null repeats without end. |
| `created_by` | VARCHAR(50) | no | The Discord id of the runner who set the rule up. |
| `created_at` | TIMESTAMP | no | When the rule was set up. Set by the database. |

# Keys and joins

[cup_occurrence](cup_occurrence.md) names the cups made from it.

# Rules

- `POST /events/{id}/recurrence` sets a rule up from a cup the caller runs, for an admin or a holder of an organizer grant; the cup must have a start, becomes the first occurrence, and a cup already in a rule answers 409. `POST /events` for a cup may carry the rule as `recurrence` and sets it up in the same transaction.
- `GET /cup-recurrences` lists every rule with its next day and its latest cup; `GET /cup-recurrences/{id}` answers the rule, its cups and its next eight days, each with the cup made on it. `GET /cup-recurrences` is edge cached as a running event for every caller, and `GET /cup-recurrences/{id}` for an anonymous caller only.
- `PUT /cup-recurrences/{id}` changes the name, the start time or the last day, and `DELETE` stops the rule and keeps every cup it made; both are for a runner of the latest cup, and a change also takes an organizer grant unless the caller is an admin.
- No job makes a cup; a runner makes each one. See [events module](../../concepts/events-module.md#recurring-cups).
