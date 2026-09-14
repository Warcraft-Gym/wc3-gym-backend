# API

* [API overview](overview.md) - Seventeen route modules under one FastAPI app, one error envelope, paging with a total header, a search language, and OpenAPI at /docs.
* [Authentication](auth.md) - A bearer token is either the admin token's JWT or a Clerk session; the claims resolve the Discord id and the role once per request, and five guards build on them.
* [Consumers of the API](consumers.md) - Who calls the backend, which routes each one reads, and which tests pin those shapes.
* [Scheduled jobs](jobs.md) - Two job routes behind a shared secret, one called daily by Vercel and one every five minutes by a Cloudflare Worker, because the hosting plan allows one cron a day.
