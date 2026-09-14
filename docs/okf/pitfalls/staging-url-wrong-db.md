---
type: Pitfall
title: The staging URL is not the served database
description: The staging connection string names the anchor database, which holds no app tables; the preview serves from the shared staging database or a branch copy.
tags: [pitfall, postgres, staging]
generated: { by: claude-code/claude-fable-5-1, at: 2026-09-14T10:00:00Z }
sources:
  - id: source
    resource: ../../../api/preview_db.py
    title: runtime_database and with_database
---

# What happened

A settings write against the raw staging URL failed with `relation "settings" does not exist`, and an alembic `current` read the wrong database.

# The rule

Resolve the name the way `api/preview_db.py` does: the branch copy if it exists, else the shared database, then rewrite the URL's database part. Compare schema state on the actual app database and on `public` tables only; Supabase carries system schemas that inflate a bare table count.
