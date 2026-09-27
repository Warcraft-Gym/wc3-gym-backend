---
type: Data Model
title: event_video
description: One video link associated with an event, with its provider, title and display order.
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
| `provider` | Video provider. |
| `video_key` | Provider video identifier, unique within the event and provider. |
| `url` | Canonical watch link. |
| `title` | Optional video title. |
| `kind` | Recording scope; unknown when full-event coverage is not established. |
| `position` | Display order within the event. |
