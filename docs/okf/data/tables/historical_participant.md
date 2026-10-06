---
type: Data Model
title: historical_participant
description: One unresolved identity scoped to an event and a source section.
resource: ../../../../app/models/event_history.py
tags: [events, data]
generated: { by: claude-code/claude-opus-5-5, at: 2026-10-06T13:39:49Z }
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
| `source_name` | The first spelling the section writes, or the kept name of a reviewed correction; never a claimed account or race. |
