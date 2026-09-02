# Pictures

## Where they live

In Vercel Blob, in the store `gnl-media`, connected to this project so `BLOB_READ_WRITE_TOKEN` is set. `teams.icon_url` holds the public URL and nothing else; the `teams.icon` bytes column is gone. A caller that reads `icon_url` off the team answer fetches the image straight from the store. A caller that still asks `GET /teams/{id}/image` pays one function invocation and one `SELECT icon_url` for the redirect, which is deliberately not cacheable: a replacement deletes the blob it replaced, so a cached redirect would point at something that no longer exists.

`POST /teams/{id}/image` uploads. It checks the magic bytes — PNG or JPEG, since three of the ten live logos are JPEGs that were stored as `image/png` — and a 2 MB cap, because the file becomes a public URL. Every upload gets a new random suffix, so replacing a logo changes its URL and no browser holds the old one behind the year-long cache; the blob it replaced is deleted straight after.

Setting a logo is still picking a file in the admin UI. That is deliberate: a season is set up without a developer, and it has to stay that way.

## Why it is not a database column any more

`Team.icon` used to be a `bytea` on the mapped row, so every `select(Team)` read the logo — including the reads that return no image, since no public model carries one. Measured on the bytes Postgres sends the app:

| route | icon on the row | icon deferred | answer |
|---|---|---|---|
| `/series/season/2` | 21,873,183 B | 83,143 B | 190,559 B |
| `/teams/season/2` | 7,803,158 B | 55,583 B | 69,992 B |
| `/teams/basic` | 888,308 B | 529 B | 1,411 B |

A season of series joins teams row by row, so it re-read the whole set many times over to answer 190 KB that contains no image bytes. That took the Supabase organisation over its 5 GB egress quota in September 2026. Browser caching could never have helped: the browser never asked for an image.

A `bytea` also crosses the wire as hex, so reading a 49 KB logo cost about 99 KB.

## What still guards it

`tests/test_blob_budget.py` walks `SQLModel._sa_registry.mappers` and fails when any mapped binary column is not deferred, and again when one exists at all. No model has one now, and that is the state to hold: a picture is a URL.

## Map pictures

The same store, under `maps/<map id>`, reached by `POST /maps/{id}/image`. `maps.image` holds the URL, and it holds a second kind: the ladder import writes the URL warcraft3.info publishes the thumbnail at, which is a CDN that costs us nothing, so those bytes are never copied into our store. `blob.ours` tells the two apart, because a replacement deletes only a blob we wrote.

An upload wins over an import: the import fills `image` only where it is empty. The map answer carries `image`, so the season pool page and the veto board render the picture without touching the backend again.

## Seeded databases

A seeded database gets its logos from the seed repo, which carries `logos/<team id>.png` or `.jpg`. `just _load-seed` pushes each through `TeamService.update_icon` after the CSVs load, so the database owns its blobs and a replaced production logo cannot break it. Without `BLOB_READ_WRITE_TOKEN` the upload is skipped and teams show the default logo.

The WordPress shortcodes are not part of this. They call `backend.warcraft-gym.com`, which is the Azure box running the older Flask app against MySQL, so they never read Supabase and never blocked any of it.
