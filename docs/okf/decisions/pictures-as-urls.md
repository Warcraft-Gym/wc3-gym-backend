---
type: Decision
title: Pictures are URLs
description: Logos and map pictures live in a blob store as public URLs, uploaded from the admin UI; no bytes column exists in the database.
tags: [storage]
generated: { by: claude-code/claude-fable-5-1, at: 2026-09-14T10:00:00Z }
sources:
  - id: source
    resource: ../../PICTURES.md
    title: Pictures
---

# Decision

Made 2026-09-02. `teams.icon` was dropped; `teams.icon_url` and `maps.image` hold URLs. The in-app upload button stays, because a season is set up without a developer.

# Why

A bytes column on the team row was read by every query that touched a team. One season page read 29.7 MB to answer 139 KB, and database egress is the metered cost. A bundled-logo frontend was reverted for the same reason: the picture must be replaceable without a deploy.

# Consequences

- `tests/test_blob_budget.py` fails on any binary column. Keep it.
- A replacement gets a new URL and deletes the old blob; a seed never copies a production URL.
See [pictures and replays](../concepts/pictures-and-replays.md).
