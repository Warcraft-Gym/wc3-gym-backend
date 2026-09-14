---
type: Pitfall
title: A boundary test that drives the oracle proves nothing
description: 71 careful boundary cases passed while the production SQL rule was broken, because the test called the Python copy in the test folder.
tags: [pitfall, tests]
generated: { by: claude-code/claude-fable-5-1, at: 2026-09-14T10:00:00Z }
sources:
  - id: source
    resource: ../../../tests/test_achievement_parity.py
    title: The parity test walks the same case table
---

# What happened

The achievement boundary tests called `tests/achievement_oracle.py`. The production rule is SQL in `app/core/achievement_shapes.py`. Changing `>=` to `>` there broke who earns a badge and every test passed. The random parity test stepped over the exact thresholds.

# The rule

When a suite has an oracle, ask which side each test drives. Feed the boundary cases through both faces. The parity test now walks the same case table.
