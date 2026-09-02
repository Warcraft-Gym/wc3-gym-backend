# Team logos

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

`Map.icon` is deferred, via `__mapper_args__ = {"properties": {"icon": deferred(icon_column)}}`. SQLModel swallows both `sa_column=deferred(...)` and `mapped_column(deferred=True)`; the mapper-args form is the one that takes.

`tests/test_blob_budget.py` walks `SQLModel._sa_registry.mappers` and fails when any mapped binary column is not deferred. It is what found `Map.icon`, which holds nothing in production and would cost the same the day someone uploaded a map picture. It guards the next binary column too.

## Seeded databases

The seed CSV carries `icon_url`, so a freshly seeded database points at the production blobs. A copy seeded before the column existed has no logo until it is seeded again; the browser shows the default logo for those.

`Map.icon` is empty in production and still written by `POST /maps/{id}/image`. `MapBase.image` is already a URL column, so whether maps follow is a separate and much smaller decision.

The WordPress shortcodes are not part of this. They call `backend.warcraft-gym.com`, which is the Azure box running the older Flask app against MySQL, so they never read Supabase and never blocked any of it.
