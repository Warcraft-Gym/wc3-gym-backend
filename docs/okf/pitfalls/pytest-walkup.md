---
type: Pitfall
title: pytest walks up to the parent checkout
description: An empty pytest table in pyproject.toml makes pytest adopt an ancestor directory as its root, which in a nested worktree is the main checkout.
tags: [testing]
generated: { by: claude-code/claude-fable-5-1, at: 2026-09-14T10:00:00Z }
sources:
  - id: source
    resource: ../../../pyproject.toml
    title: The pytest table
---

# What happened

pytest accepts a `pyproject.toml` as its config only when the `[tool.pytest]` table is not empty. With an empty table, root discovery walked up from a worktree under the checkout, adopted the checkout's `pyproject.toml`, and applied its `pythonpath` relative to the checkout, so the checkout's `app/` silently supplied imports.

# The rule

Keep `[tool.pytest]` non-empty (it holds `testpaths`). When pytest behaves impossibly in a worktree, read `rootdir:` and `configfile:` in its header first. The native `[tool.pytest]` table is the modern form on pytest 9; do not rename it to `ini_options`.
