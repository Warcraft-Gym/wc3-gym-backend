---
type: Pitfall
title: Quoting a whole relationship annotation breaks every mapper
description: A SQLModel Relationship annotated as the string "X | None" hands SQLAlchemy an opaque name; X | None works when X is imported, and Optional["X"] is the only quoted form.
tags: [data]
generated: { by: claude-code/claude-fable-5-1, at: 2026-10-06T10:27:53Z }
sources:
  - id: source
    resource: ../../../app/models/relationships.py
    title: The three attributes that keep Optional
---

# What happened

Modernising `Optional["X"]` to `"X | None"` made every mapper fail with `failed to locate a name`. SQLModel unwraps a real union to its non-None arm and hands a bare forward reference through as a string; a quoted union is one opaque string.

# The rule

`X | None` on a relationship needs `X` to be a real object at class creation. A target importable only under `TYPE_CHECKING`, because of an import cycle, keeps `Optional["X"]` with a comment saying why. Two attributes in the app do, both on `DraftSeries`. Before assuming a relationship must keep `Optional`, look for the cycle.
