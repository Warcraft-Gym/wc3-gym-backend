---
type: Data Model
title: settings
description: One key-value row per runtime setting an admin edits, including the two season pointers and the Discord channel ids.
resource: ../../../../app/models/settings.py
tags: [auth, data]
generated: { by: claude-code/claude-fable-5-1, at: 2026-09-14T15:15:00Z }
verified: { by: process:test_okf, at: 2026-09-14T17:40:50Z }
sources:
  - id: model
    resource: ../../../../app/models/settings.py
    title: Settings
  - id: service
    resource: ../../../../app/services/settings.py
    title: SettingsService
---

# Schema

| Column | Type | Null | Meaning |
|---|---|---|---|
| `id` | INTEGER | no | Primary key. |
| `key` | VARCHAR | no | The setting name. Unique. The known keys are listed in [settings and the current season](../../concepts/settings-and-current-season.md). |
| `value` | VARCHAR | yes | The value as text. A caller that sends a number gets it stored as its string form. Null means the key exists with no value. |
| `description` | VARCHAR | yes | A free-text note an admin wrote about the row. |

# Keys and joins

Primary key `id`. Unique index on `key`. No foreign keys. Nothing points at this table.

# Rules

A missing `current_gnl_season` row falls back to the newest season. `current_w3c_season` is a hand edit that must keep winning over the derived value. See [the decision](../../decisions/season-boundary-manual.md).
