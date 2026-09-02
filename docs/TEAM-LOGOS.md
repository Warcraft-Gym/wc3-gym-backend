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

- Serving a logo still reads it out of Postgres when the Vercel CDN does not already hold it. The response carries `Cache-Control: public, max-age=86400` and the CDN does cache it (`x-vercel-cache: HIT`), so a repeat costs nothing; a cold edge costs one read.
- The ETag is computed from the blob, so a read that ends in a 304 still pulled the whole thing first.
- A `bytea` value crosses the wire as hex, so a 49 KB logo costs about 99 KB of egress when it is read.
- The database still carries binary data, which is what the free Supabase plan assumes it will not.

## Who reads these logos

Only the Vue app, through `wc3-gym-backend-snowy.vercel.app`. The WordPress shortcodes call `backend.warcraft-gym.com`, which is the Azure box running the older Flask app against MySQL (`server: Caddy`/`gunicorn`, `etag: team-5`), so they never touch Supabase and are not part of this. That matters for sequencing: nothing in WordPress blocks changing how the app stores logos.

## Moving them out

Two constraints pulling in opposite directions: a non-developer has to be able to set a logo, and the database should not carry binary data.

| option | keeps the upload button | notes |
|---|---|---|
| Vercel Blob with an upload route | yes | official Python SDK (`vercel` on PyPI); Hobby includes 1 GB storage and 10 GB transfer, and exceeding it removes Blob for 30 days rather than billing |
| Supabase Storage bucket | yes | served through the Smart CDN this counts as *cached* egress, a [separate 5 GB quota](https://supabase.com/docs/guides/platform/manage-your-usage/egress) from the 5 GB the database draws on, so it does help |
| a URL column, image hosted elsewhere | no, it becomes upload-then-paste | none |

`MapBase.image` is already a URL column, so the shape exists in the codebase. Whichever store is chosen, the upload route keeps its signature so the workflow does not change, and `teams.icon` can be dropped once the ten existing logos are copied across.
