---
type: Data Model
title: koth_history_series
description: The source row behind one imported competitive BO1 series.
resource: ../../../../app/models/event_history.py
tags: [events, data]
generated: { by: claude-code/claude-opus-5-5, at: 2026-10-06T16:17:32Z }
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
| `inferred_winner` | Side 1 or 2 inferred from winner-stays-on order for a series the source page writes no winner for; null where the order does not show one. Shown on the board, never written to the series score. |
| `review_note` | Why this series has no inferred winner: a source note in the page's words, a rematch next, a name close to one in the next series, no king, or a king outside the last series. "The winner does not play the next series" marks a series whose winner, written or not known, left the throne after it; the board reads it as `winner_left`. |
