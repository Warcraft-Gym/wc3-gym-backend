---
type: Data Model
title: koth_history_series
description: The source row behind one imported competitive BO1 series.
resource: ../../../../app/models/event_history.py
tags: [events, data]
generated: { by: codex/gpt-6-sol, at: 2026-09-26T04:00:00Z }
sources:
  - id: model
    resource: ../../../../app/models/event_history.py
    title: Archive models
---

# Schema

| Column | Meaning |
|---|---|
| `series_id` | Primary key and series reference; cascades on deletion. |
| `event_id` | Owning event; cascades on deletion. |
| `source_key` | Section and row ordinal, unique within the event. |
| `source_record` | Private original pairing and annotations; independent of inferred identity. |
