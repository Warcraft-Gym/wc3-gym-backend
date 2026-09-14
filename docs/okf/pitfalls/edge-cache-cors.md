---
type: Pitfall
title: The edge cache stores the CORS header
description: A publicly cached route filled by a client with no Origin header is stored without the CORS header, and every browser then blocks it.
tags: [api, deploy]
generated: { by: claude-code/claude-fable-5-1, at: 2026-09-14T10:00:00Z }
sources:
  - id: source
    resource: ../../../app/main.py
    title: The CORS middleware
---

# What happened

`GET /seasons/{id}/ladder` sets `Cache-Control: public, s-maxage=...`. Starlette's CORS middleware adds `Access-Control-Allow-Origin` only when the request carries an `Origin`, and with every origin allowed it adds no `Vary: Origin`. A fill by curl, a bot or an uptime check stored a copy with no CORS header. Browsers then read that copy and blocked it; Firefox reported `NetworkError when attempting to fetch resource`, which reads like a dead server. The entry healed when the cache expired and broke again on the next non-browser fill.

# The rule

A route that sets `Cache-Control: public` writes `Access-Control-Allow-Origin: *` itself, beside it. Test it with a client that sends no `Origin`. Reproduce with a cache-buster query so the real key is untouched. The frontend sends no bearer on that route, because a request with an Authorization header is never cached.
