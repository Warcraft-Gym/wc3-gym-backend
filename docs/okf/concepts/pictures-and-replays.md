---
type: Integration
title: Pictures and replays
description: Team logos and map thumbnails live in Vercel Blob as public URLs, replays live in a Cloudflare R2 bucket reached through presigned URLs, and both stores follow the rows.
resource: ../../PICTURES.md
tags: [storage]
generated: { by: claude-code/claude-opus-5-5, at: 2026-09-24T00:00:00Z }
sources:
  - id: pictures
    resource: ../../PICTURES.md
    title: Pictures
  - id: blob
    resource: ../../../app/services/blob.py
    title: The blob store
  - id: r2
    resource: ../../../app/services/r2.py
    title: The replay bucket
---

# Pictures

`teams.icon_url` and `maps.image` hold public URLs into a Vercel Blob store, one per environment: `gnl-media` for production, `gnl-media-staging` for preview and development. Calls authenticate with `BLOB_STORE_ID` and the Vercel OIDC token, which only the connected store accepts, so no environment can delete another's files. A caller that reads the URL off the answer fetches the picture from the store; `GET /leagues/{league_id}/teams/{team_id}/image` still redirects, uncacheable, for the old consumers. `POST /leagues/{league_id}/teams/{team_id}/image` and `POST /maps/{id}/image` upload: magic bytes checked, 2 MB cap, a new random suffix per upload so the year-long cache never serves a stale logo, and the blob it replaced deleted after the commit.

A map's `image` may also hold the URL warcraft3.info publishes, written by the ladder map import; `blob.ours` tells the two apart, so a replacement deletes only a blob the app wrote. An upload wins over an import.

The store follows the rows: a deleted team or map drops its picture after the commit. The listeners are registered on the session in `app/core/db.py`.

The SDK is imported inside each call, because it carries its own HTTP stack and only the upload path needs it.

# Why not in the database

`Team.icon` used to be a bytes column, so every `select(Team)` read the logo: one season page read 29.7 MB of the database to answer 139 KB, and database egress is the metered cost. `tests/test_blob_budget.py` fails on any mapped binary column. A picture is a URL. See [the pitfall](../pitfalls/blob-egress.md) and [the decision](../decisions/pictures-as-urls.md).

# Replays

Replays live in one Cloudflare R2 bucket per environment, named by `CLOUDFLARE_R2_BUCKET`, each with its own scoped API token (`CLOUDFLARE_ACCOUNT_ID`, `CLOUDFLARE_R2_BUCKET`, `CLOUDFLARE_ACCESS_KEY_ID`, `CLOUDFLARE_SECRET_ACCESS_KEY`). Every call is a presigned URL signed with the standard library, so the browser uploads straight to the bucket and no file crosses a Vercel function's 4.5 MB request cap. A download link lives as long as R2 allows; an old tab gets a 403 and refreshes. A key starts with `VERCEL_ENV`, so two builds never share a file. A deleted series drops its files after the commit. A replay moves between the games of its series on one call, and the file changes place in the bucket with it, so a game slot always holds the key built from its own series and game number; that move is the only path where a replay passes through a function.

A `.w3g` file gives up the map and both battle tags from its first inflated block. It does not give up the winner; do not build a parser that walks its records to guess one.

# Seeding

A seeded database gets its logos from the private seed repository, pushed through the same upload path by `just _load-seed`, so the database owns its blobs and a replaced production logo cannot break it. Without the token the load stops after the CSVs and teams show the default logo.
