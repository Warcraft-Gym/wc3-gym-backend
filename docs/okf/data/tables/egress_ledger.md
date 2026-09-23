---
type: Data Model
title: egress_ledger
description: "What each route cost the database, one row per day, route and method: calls, statements, rows and response bytes."
resource: ../../../../app/models/egress_ledger.py
tags: [deploy, data]
generated: { by: claude-code/claude-opus-5-5, at: 2026-09-23T12:40:00Z }
sources:
  - id: model
    resource: ../../../../app/models/egress_ledger.py
    title: EgressLedger
  - id: middleware
    resource: ../../../../app/main.py
    title: EgressMiddleware adds every request to the row
  - id: service
    resource: ../../../../app/services/egress.py
    title: record and recent
---

# Schema

| Column | Type | Null | Meaning |
|---|---|---|---|
| `day` | DATE | no | The UTC day of the calls. |
| `route` | TEXT | no | The route template, for example `/events/{event_id}/series`. |
| `method` | TEXT | no | The HTTP method. |
| `calls` | BIGINT | no | Requests to the route that day. |
| `statements` | BIGINT | no | Statements the calls sent to the database. |
| `rows` | BIGINT | no | Rows returned by reads plus rows changed by writes, from the driver's rowcount. |
| `bytes` | BIGINT | no | Response bytes, from the content length; 0 for a streamed body. |

# Keys and joins

Primary key (`day`, `route`, `method`). No foreign keys.

# Rules

The middleware in `app/main.py` adds one call to the row after each request, in one upsert that does not count toward the request. A 404 or a 405 is not recorded, and neither is `GET /jobs/egress`, the route that reads the table. Statements a background task runs after the response count in the ledger but not in the response headers, which are sent before them. A failed write is logged and never fails the request. See [scheduled jobs](../../api/jobs.md).
