---
type: Pitfall
title: Every datetime is aware UTC
description: A stale log line said the backend stored Eastern time and cost a whole wrong work package; times are UTC, stored aware, and the public site once added five hours.
tags: [data]
generated: { by: claude-code/claude-fable-5-1, at: 2026-09-14T10:00:00Z }
sources:
  - id: source
    resource: ../../../app/models/types.py
    title: UTCDateTime and AwareUTC
---

# What happened

A stale log line once claimed the series time was stored as Eastern time; the backend stores what it is handed and the frontend sends UTC. A zone read off a comment instead of the write path leads to migration work that is not needed. The public site's shortcode added five hours to every series time on the same false premise. Reading a season window in the wrong zone changes the ladder results of about one player in seven.

# The rule

- Every stored datetime is `timestamptz`; every input is aware UTC through `AwareUTC`; responses end in `Z`.
- Before believing a comment about a zone, find the write path.
- Rows from a workbook import carry whatever zone the sheet used; spot-check before assuming.
