# API

* [API overview](overview.md) - Twenty-one route modules under one FastAPI app, one error envelope, paging with a total header, a search language, and OpenAPI at /docs.
* [Authentication](auth.md) - A bearer token is either the admin token's JWT or a Clerk session; the claims resolve the Discord id and the role once per request, and five guards build on them.
* [Consumers of the API](consumers.md) - Who calls the backend, which routes each one reads, which tests pin those shapes, and the rules a consumer follows to keep reads off the database.
* [Response shapes](response-shapes.md) - An entity inside another answer is its summary shape, bounded by the read's event; the detail comes only from the entity's own read, and a write answers through that read.
* [Scheduled jobs](jobs.md) - Five job routes behind a shared secret, two called daily by Vercel, one every five minutes by a Cloudflare Worker because a Vercel cron runs at most once a day, and two an operator reads for egress.
