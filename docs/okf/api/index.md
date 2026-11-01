# API

* [API overview](overview.md) - Twenty-three route modules under one FastAPI app, one error envelope, paging with a total header, a search language, and OpenAPI at /docs.
* [Authentication](auth.md) - A bearer token is the admin token's JWT or a member's Discord session, both signed by the backend; the claims resolve the Discord id and the role once per request, and five guards build on them.
* [Consumers of the API](consumers.md) - Who calls the backend, which routes each one reads, which tests pin those shapes, and the rules a consumer follows to keep reads off the database.
* [Response shapes](response-shapes.md) - An entity inside another answer is its summary shape, bounded by the read's event; the detail comes only from the entity's own read, a write answers through that read, and the relationships of the main models refuse an on-the-spot load.
* [Scheduled jobs](jobs.md) - Five job routes behind a shared secret, two called daily by Vercel, one by a Cloudflare Worker whenever a reminder or a cup call falls due, and two an operator reads for egress.
