---
type: Data Model
title: historical_participant
description: One archived name scoped to an event and a source section, linked to a player once a review names one.
resource: ../../../../app/models/event_history.py
tags: [events, data]
generated: { by: claude-code/claude-opus-5-5, at: 2026-10-08T12:00:00Z }
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
| `source_name` | The kept name of a reviewed correction, else the spelling of the section's last crown line that crowns the participant, else the first spelling the section's series write; never a claimed account or race. |
| `user_id` | The player a reviewed link says wrote under this name, set by the importer's `link_players` from a name to battle tag list; null until linked, and set null when the player is deleted. |
