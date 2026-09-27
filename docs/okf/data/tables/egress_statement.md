---
type: Data Model
title: egress_statement
description: "The text of each statement in egress_snapshot, stored once: the first 150 characters with whitespace collapsed."
resource: ../../../../app/models/egress_snapshot.py
tags: [deploy, data]
generated: { by: claude-code/claude-opus-5-5, at: 2026-09-26T10:00:00Z }
sources:
  - id: model
    resource: ../../../../app/models/egress_snapshot.py
    title: EgressStatement
  - id: service
    resource: ../../../../app/services/egress_snapshot.py
    title: take
---

# Schema

| Column | Type | Null | Meaning |
|---|---|---|---|
| `queryid` | BIGINT | no | The statement's `queryid` in pg_stat_statements. |
| `dbid` | BIGINT | no | The oid of the database the statement ran in. |
| `query` | TEXT | no | The first 150 characters of the normalised statement, whitespace collapsed. |

# Keys and joins

Primary key (`queryid`, `dbid`). [egress_snapshot](egress_snapshot.md) rows join on the same two columns. No foreign keys.

# Rules

The snapshot job adds the text of a statement it has not seen and never rewrites one. After it deletes the snapshots older than 35 days it deletes the texts no snapshot names.
