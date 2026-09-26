---
type: Data Model
title: historical_participant
description: One unresolved identity scoped to an event and a source section.
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
| `id` | Primary key. |
| `event_id` | Owning event; cascades on deletion. |
| `source_key` | Immutable section-local source key; unique within the event. |
| `source_name` | Literal source label, without a claimed account or race. |
