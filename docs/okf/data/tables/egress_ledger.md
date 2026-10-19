---
type: Data Model
title: egress_ledger
description: "What each route cost the database and the process, one row per day, route and method: calls, statements, rows, response bytes and CPU."
resource: ../../../../app/models/egress_ledger.py
tags: [deploy, data]
generated: { by: claude-code/claude-opus-5-5, at: 2026-10-19T09:00:00Z }
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
| `db_bytes` | BIGINT | no | Bytes the calls' database connections received, as the kernel counts them on the socket: the egress the pooler bills. |
| `bytes` | BIGINT | no | Response bytes, from the content length; 0 for a streamed body. |
| `cpu_ms` | BIGINT | no | Process CPU in milliseconds, user and system, spent since the ledger write before. |

# Keys and joins

Primary key (`day`, `route`, `method`). No foreign keys.

# Rules

The middleware in `app/main.py` adds one call to the row after each request, in one upsert that does not count toward the request. A 404 or a 405 is not recorded, and neither is `GET /jobs/egress`, the route that reads the table. Statements a background task runs after the response count in the ledger but not in the response headers, which are sent before them. A failed write is logged and never fails the request. `db_bytes` is read from the socket's `TCP_INFO` each time a connection returns to the pool: what it received since its last return goes to the request that held it, the connect handshake, the ping, every result and the commit included. Traffic from outside the app, a migration or a script, is not in the ledger. `cpu_ms` is read from the process clock before each write: requests that overlap, and the requests the ledger skips, shift CPU between routes, and a day's sum is exact. A process's first write adds one row more, route `(startup)` and method `-`, with one call and the CPU spent before it: the import, the app build and the requests up to that write. Its `calls` count the processes started that day. See [scheduled jobs](../../api/jobs.md).
