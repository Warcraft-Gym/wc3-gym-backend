---
type: Integration
title: Map sources
description: The sites the app takes maps from, each one module behind one contract, which an organizer or an admin picks maps from and the ladder import asks in a fixed order.
resource: ../../../app/services/map_sources/__init__.py
tags: [maps]
generated: { by: claude-code/claude-opus-5-5, at: 2026-11-01T12:00:00Z }
sources:
  - id: registry
    resource: ../../../app/services/map_sources/__init__.py
    title: The registry and the ladder's order
  - id: base
    resource: ../../../app/services/map_sources/base.py
    title: The contract and the shared reads
  - id: service
    resource: ../../../app/services/maps.py
    title: The imports
  - id: tests
    resource: ../../../tests/test_map_sources.py
    title: The contract, tested on a fake source
---

# The sources

| Key | Holds | Pictures |
|---|---|---|
| `liquipedia` | a page per map, the number of players, no short name | copied into our store during an import, because the wiki refuses its files to a page on another site; its rows credit it under CC-BY-SA 3.0 |
| `warcraft3_info` | every published map and version, its short name, the modes it is tagged with | kept at the URL it publishes them at |

`SOURCES` in `app/services/map_sources/__init__.py` is the registry, in the order `GET /maps/sources` lists it. `LADDER_ORDER` names the order the ladder import asks in, warcraft3.info first because it alone holds short names.

# What a source implements

A source is a class with `key`, `title`, `credit_url`, `license` and `copies_pictures`, and two methods.

- `catalogue(q)` answers at most 500 maps whose name holds the search, a cap above what the sites hold so that a page can filter a whole list. A site with a small list reads it once and filters it with `matching`. A site too large for that searches remotely, which is why the search is part of the contract. A page shows a row's picture straight from the site, so a site that refuses that lists none.
- `find(names)` answers the source's best match per name it knows, with its picture. Each source matches in its own way. warcraft3.info keeps every version under its own name, so the version decides, and with no version to go by the entry with the most files. Liquipedia folds a name to its lineage with `folded_base`, then prefers the page of the same version.

Both raise `ExternalServiceError` when the site cannot be read.

# Reading a site

- A source reads through `base.read` and `base.read_json`, which send one User-Agent naming the app and its public repository. A read never imitates a browser and never answers a challenge. A site that refuses is treated as not read, and a page never drops its referrer to show a picture a site refuses it.
- A failure names the host and the status, and never carries the page the site answered with.
- A process keeps a source's whole list for a day (`remember`). Liquipedia's calls stay two seconds apart (`API_PAUSE`), as its terms set. Its HTML pages are never read: its terms allow the API alone.

# Importing from a site

All three routes take an organizer or an admin and are never cached. An import touches only the maps picked.

- `GET /maps/sources` lists the sources with their credit.
- `GET /maps/sources/{key}?q=` lists a source's maps. Each row carries the map of the app it is (`map_id`, found by name, else by its one lineage twin) and whether that map has a picture (`pictured`). A name longer than the table holds is not offered.
- `POST /maps/sources/{key}` takes `{maps: [{name, modes}]}`, at most 10 per call so that a call copying its pictures fits the function's time limit. A new map takes the source's short name, else unique initials, and the modes chosen. A map the app holds gains the modes and a missing picture, and keeps its name and short name.

An unknown key answers 404. A source that cannot be read answers 502 and writes nothing.

# The ladder import

`GET` and `POST /maps/ladder-import` and their `/events/{event_id}` twins read W3Champions for the ladder, then ask the sources only for the maps that are new or have no picture. When every map is held and pictured, no source is read. A map whose name leaves its version out is asked for with the version in its file path.

`find_in_order` asks each source in `LADDER_ORDER` for the names still open. A source that cannot be read is logged and the next one is asked. Each row names the source that knew the map (`source`) and every source that could not be read (`unreached`), and a page says so. A row shows a picture only from a source that keeps its pictures at their URL. A copied one shows once it is ours. A map no source knows gets its initials and no picture. W3Champions itself failing answers 502.

# Pictures

`copies_pictures` decides. A linked picture is written as its URL. A copied one is downloaded through `base.read` and stored through the upload path, so it passes the same magic-bytes check and 2 MB cap. Both happen after the maps are committed and only for a map that still has no picture, so an upload always wins. A picture that cannot be copied, or that the store cannot take, is logged and the map stays without one, and the next import tries again. The answer carries each map's `image`, so a page can name the maps without one. One call stops copying after 40 seconds (`COPY_SECONDS`) so that it ends inside the function's time limit, and the next import fills what is left. See [pictures](pictures-and-replays.md).

# Adding a site

1. Check that the site offers an API and that its terms allow this use. Do not write a module for a site that does not.
2. Add one module under `app/services/map_sources/`, reading through `base.read_json`.
3. Add its instance to `SOURCES`, and its key to `LADDER_ORDER` only if the ladder import should ask it.
4. Set `copies_pictures` and the credit its terms ask for. Copy when the site refuses its files to a page on another site, and check that in a browser, because the refusal can arrive as a picture that loads. The dialog shows the credit with the source's rows. A site whose pictures the web app shows is also named on the web app's Credits page.

The routes and the dialog list every source in `SOURCES`, so no other route or dialog changes.
