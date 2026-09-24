---
type: API Area
title: Consumers of the API
description: Who calls the backend, which routes each one reads, which tests pin those shapes, and the rules a consumer follows to keep reads off the database.
resource: ../../../tests/test_public_contract.py
tags: [api]
generated: { by: claude-code/claude-opus-5-5, at: 2026-09-24T18:30:00Z }
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
  - id: event-season-parity
    resource: ../../../tests/test_event_season_parity.py
    title: The event replacement for season routes
---

# The consumers

| Consumer | Repository | Reads | Auth |
|---|---|---|---|
| the web app | `wc3-gym-frontend` | most routes | Clerk session or the admin token |
| the GNL website | `wc3-gnl-website` | server-side, from Next.js: `GET /leagues`, `GET /events`, `GET /leagues/{league_id}/teams`, and for finished events `/events/{event_id}/teams`, `/series`, `/ladder` and `/fantasy/teams`; for a player `GET /users/{user_id}`, `GET /users/{user_id}/history` and `GET /stats/career` | none |
| the WordPress site | `gym_website_scripts` | eight paths on every page view, no cache, against the older backend host: `GET /stats/career`, `GET /config/settings`, `GET /teams/season/{id}`, `GET /teams/{id}/image`, `GET /seasons/{id}`, `POST /matches/search`, `POST /series/season/{id}/playday/{n}/search`, `POST /fantasy/teams/search` | none |
| the Discord adapter | `wc3-gym-discord-bot` | `POST /discord/interactions` | Discord's signature |
| the cast-reminder worker | `wc3-gym-discord-bot`, `cron/` | `GET /jobs/cast-reminders` every five minutes | `CRON_SECRET` bearer |
| Vercel cron | this repository's `vercel.json` | `GET /jobs/w3c-sync` once a day | `CRON_SECRET` bearer |
| Nightbot | no repository | `GET /koth/signup`, and the deprecated `/koth/*` reads | the Nightbot token |
| the stream overlay and bookmarks | none | the deprecated `/koth/*` reads | none |

The WordPress shortcodes today call the older backend host, not this deployment, and that host answers 502, so the shortcodes show no data. Three of their paths do not exist here: `GET /teams/season/{id}`, `GET /seasons/{id}` and `POST /series/season/{id}/playday/{n}/search`. Before the shortcodes point at this deployment, those calls move to `GET /events/{id}/teams`, `GET /events/{id}` and `POST /events/{id}/rounds/{n}/series/search`. `GET /events/{id}` is not the old season payload: it has no `user_signup` or `signup_race`, and its `phase` and `signups_open` follow the event model, so the PHP that reads those fields changes with the move.

# What pins the shapes

- `tests/test_public_contract.py`: presence and shape of the fields the PHP reads, route by route.
- `tests/test_contract.py`: the fields the offline leaderboard reads.
- `tests/test_gnl_snapshot.py`: the GNL season, dashboard and card payloads byte for byte against `tests/data/gnl_snapshot.json`. Set `UPDATE_GNL_SNAPSHOT=1` to rewrite it, and read the diff: a change to it is a change to a public contract.
- `tests/test_event_season_parity.py`: GNL creation through `/events`, the GNL fields on `EventPublic`, the event routes for season subresources, and that no `/seasons` route exists.
- `tests/test_error_envelope.py`: the `error` key every client reads.
- `tests/test_paging.py`: the paged routes, their default order and sort names.

A change that fails one of these is a cross-repository change. Ship the consumer's change, or keep the old field beside the new one for a deploy.

# Rules a consumer can rely on

- Every error is `{"error": ...}`.
- A field is added, never renamed in place. `week_map_id` on the veto board and `playday` on fixtures are examples of names kept for consumers.
- The GNL season payloads keep `season_id`, `phase` and `playday` although the table is `event`.
- Consumers use the league routes for team identity and the event routes for GNL data. The one unscoped team route is `GET /teams/{team_id}/image`, deprecated, which the web app's logo fallback reads.
- List routes page with `limit` and `offset` and answer `X-Total-Count`.
- Reads are open. Writes need an admin, or the owning member for self-service routes.

# Rules a consumer follows

The database cost of a read is the rows one call reads times the number of calls that reach the function. See [what a read costs](overview.md#what-a-read-costs).

- Send no Authorization header on an open read. The edge never stores or serves a request that carries one, so a bearer turns every call into a database read. The web app does this with its `EDGE_CACHED` pattern.
- Cache on the consumer's side as well, for as long as the data allows. A finished event changes only when an admin corrects it, so a page that shows one can hold it for an hour or more. A running event's results can be held for minutes.
- Read the narrowest route that answers the page: `GET /stats/career/{user_id}` for one player, not `GET /stats/career`. When no narrow route exists, ask for one instead of filtering a list on the consumer.
- A list route answers one page, at most 500 rows by default. Read `X-Total-Count` and page with `offset` when a list can be longer.
- Local development of a consumer points at a local server (`just serve`), never at production. A development server fetches on every reload.
