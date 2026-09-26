---
type: Data Model
title: koth_history_event
description: The immutable source capture and import provenance for one historical KOTH event.
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
| `event_id` | Primary key and owning event; cascades on deletion. |
| `source_key` | Unique capture event key. |
| `source_url` | Original page reference. |
| `source_digest` | Digest of the canonical source record. |
| `date_label` | Literal source date label, including unresolved dates. |
| `source_record` | Private structured source evidence, including excluded rows. |
| `imported_at` | When the capture was imported, not the historical event time. |
