---
type: API Area
title: Consumers of the API
description: Who calls the backend, which routes each one reads, and which tests pin those shapes.
tags: [api, contract, consumers]
generated: { by: claude-code/claude-fable-5-1, at: 2026-09-14T10:00:00Z }
sources:
  - id: public-contract
    resource: ../../../tests/test_public_contract.py
    title: The fields the WordPress shortcodes read
  - id: contract
    resource: ../../../tests/test_contract.py
    title: The fields the offline leaderboard reads
  - id: snapshot
    resource: ../../../tests/test_gnl_snapshot.py
    title: The GNL payloads pinned
---

# The consumers

| Consumer | Repository | Reads | Auth |
|---|---|---|---|
| the web app | `wc3-gym-frontend` | most routes | Clerk session or the admin token |
| the WordPress site | `gym_website_scripts` | eight routes on every page view, no cache: `GET /stats/career`, `GET /config/settings`, `GET /teams/season/{id}`, `GET /teams/{id}/image`, `GET /seasons/{id}`, `POST /matches/search`, `POST /series/season/{id}/playday/{n}/search`, `POST /fantasy/teams/search` | none |
| the Discord adapter | `wc3-gym-discord-bot` | `POST /discord/interactions` | Discord's signature |
| the cast-reminder worker | `wc3-gym-discord-bot`, `cron/` | `GET /jobs/cast-reminders` every five minutes | `CRON_SECRET` bearer |
| Vercel cron | this repository's `vercel.json` | `GET /jobs/w3c-sync` once a day | `CRON_SECRET` bearer |
| Nightbot | no repository | `GET /koth/signup`, the old `/koth/*` reads | the Nightbot token |
| the stream overlay and bookmarks | none | the old `/koth/*` reads | none |

The WordPress shortcodes today call the older backend on the Azure box, not this deployment. When they move, the eight routes above are the contract.

# What pins the shapes

- `tests/test_public_contract.py`: presence and shape of the fields the PHP reads, route by route.
- `tests/test_contract.py`: the fields the offline leaderboard reads.
- `tests/test_gnl_snapshot.py`: the GNL season, dashboard and card payloads byte for byte against `tests/data/gnl_snapshot.json`. Set `UPDATE_GNL_SNAPSHOT=1` to rewrite it, and read the diff: a change to it is a change to a public contract.
- `tests/test_error_envelope.py`: the `error` key every client reads.
- `tests/test_paging.py`: the paged routes, their default order and sort names.

A change that fails one of these is a cross-repository change. Ship the consumer's change, or keep the old field beside the new one for a deploy.

# Rules a consumer can rely on

- Every error is `{"error": ...}`.
- A field is added, never renamed in place. `week_map_id` on the veto board and `playday` on fixtures are examples of names kept for consumers.
- The GNL season payloads keep `season_id`, `phase` and `playday` although the table is `event`.
- List routes page with `limit` and `offset` and answer `X-Total-Count`.
- Reads are open. Writes need an admin, or the owning member for self-service routes.
