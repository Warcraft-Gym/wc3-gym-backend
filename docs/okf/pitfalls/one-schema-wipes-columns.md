---
type: Pitfall
title: One schema per entity wipes columns
description: A single model serving create, update and response made every field optional, and an update wrote every column, nulling the ones the request left out.
tags: [pitfall, sqlmodel]
generated: { by: claude-code/claude-fable-5-1, at: 2026-09-14T10:00:00Z }
sources:
  - id: source
    resource: ../../../app/models/user.py
    title: A family with a separate Update shape
---

# What happened

`PUT /users/{id}` with only an `mmr` answered 500 because it also set the required `name` to null. A nullable column in the same position was erased silently. Three internal callers also handed a response object to an update and failed with `'dict' object has no attribute '_sa_instance_state'`.

# The rule

Every entity has an Update shape with every field optional, applied with `model_dump(exclude_unset=True)`. An update takes an Update built from the fields it means to change, never a Public read back. See [model families](../data/model-families.md).
