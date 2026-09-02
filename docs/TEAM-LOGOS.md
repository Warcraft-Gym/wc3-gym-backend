# Team logos

## Where they live today

A team logo is a PNG in `teams.icon`, a `bytea` column, uploaded through `POST /teams/{id}/image` and served by `GET /teams/{id}/image` with `Cache-Control: public, max-age=86400` and an ETag. The ten logos are 32-64 KB each, 444 KB together.

**This is an interim arrangement, not the intended end state.** It survives because the upload button is how a season gets set up without a developer: Barren adds the teams and their logos himself. Any replacement has to keep that true.

## Why the column is deferred

`Team.icon` and `Map.icon` are mapped with `__mapper_args__ = {"properties": {"icon": deferred(icon_column)}}`. Without that, the column sits on the mapped row and every `select(Team)` reads the logo, including the reads that never return an image. Measured on the bytes Postgres sends the app, against the seed database:

| route | icon on the row | icon deferred | answer |
|---|---|---|---|
| `/series/season/2` | 21,873,183 B | 83,143 B | 190,559 B |
| `/teams/season/2` | 7,803,158 B | 55,583 B | 69,992 B |
| `/teams/basic` | 888,308 B | 529 B | 1,411 B |

A season of series joins teams row by row, so it read the whole 444 KB set roughly 49 times over to answer 190 KB that contains no image bytes at all. That is what took the Supabase organisation over its 5 GB egress quota in September 2026.

Browser caching cannot help with any of this, because the browser never asked for an image. The cache on `GET /teams/{id}/image` works and always did; that route was never the problem.

`tests/test_blob_budget.py` fails when any mapped binary column is not deferred, so this cannot regress quietly. It is what found `Map.icon`, which held nothing yet and would have cost the same the day someone uploaded a map picture.

## What the deferral does not fix

- Serving a logo still reads it out of Postgres, about 99 KB per logo per browser per day.
- The ETag is computed from the blob, so even a 304 reads the whole icon first.
- The database still carries binary data, which is what the free Supabase plan assumes it will not.

## Moving them out

Two constraints, and they pull in opposite directions: a non-developer has to be able to set a logo, and the database should not carry binary data.

**Supabase Storage does not solve the egress half.** The 5 GB is a [unified egress quota](https://supabase.com/docs/guides/platform/manage-your-usage/egress) covering Database, Auth, Storage, Realtime, Edge Functions and Log Drains. Moving the bytes from the database to a Supabase bucket moves them between meters inside the same pool.

Anything hosted outside Supabase does solve it:

| option | keeps the upload button | egress cost |
|---|---|---|
| object storage with an upload route (Cloudflare R2, Vercel Blob) | yes | R2 charges nothing for egress |
| a URL column, image uploaded to the WordPress media library | no, it becomes upload-then-paste | none, WordPress already hosts it |
| bundled in the frontend build | no, a logo change becomes a pull request | none |

Object storage is the only one of the three that keeps the workflow intact: the app keeps its upload button, writes the file to the bucket instead of the column, and stores the key. `MapBase.image` is already a URL column, so the shape exists in the codebase.

Whatever replaces it, `gym_website_scripts` reads `backend.warcraft-gym.com/teams/<id>/image` too, so the route and the column stay until that moves as well.
