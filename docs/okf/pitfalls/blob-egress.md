---
type: Pitfall
title: A bytes column drives egress
description: A picture stored as bytes on a row is read by every query that touches the row, invisible to statement counts and response sizes, and it drove database egress.
tags: [data]
generated: { by: claude-code/claude-fable-5-1, at: 2026-09-14T10:00:00Z }
sources:
  - id: source
    resource: ../../PICTURES.md
    title: Why it is not a database column any more
---

# What happened

`Team.icon` was a plain bytes column. Measured on the wire, `/series/season/2` read 21.9 MB to answer 190 KB, and `/teams/season/2` read 7.8 MB to answer 70 KB. The statement-count test passed the whole time: an N+1 that re-reads a blob shows in neither statements nor response sizes. Supabase meters bytes leaving the database, so this was the cost driver. A bytes column also crosses the wire as hex, doubling it.

# The rule

- A picture is a URL. `tests/test_blob_budget.py` fails on any mapped binary column; keep it.
- Measure this class of problem with a byte-counting relay in front of Postgres, never by reading response sizes.
- The older self-hosted backend serves the WordPress site from another host; never scale a production figure from that host.
