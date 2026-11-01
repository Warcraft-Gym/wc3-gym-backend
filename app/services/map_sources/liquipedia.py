"""Liquipedia: the wiki's map pages, read through its MediaWiki API.

Its terms allow this use: an identifying User-Agent, gzip, at most one call every
two seconds, cached results, and its text and media credited under CC-BY-SA. They
forbid automated reads of its HTML pages, so nothing here reads one.

A page is titled with the map's base name, and its categories name the players.
The wiki keeps no short name.
"""

import re
from dataclasses import replace
from itertools import batched
from time import monotonic, sleep
from typing import Any

from app.core.exceptions import ExternalServiceError
from app.services.ladder_maps import folded_base, split_version
from app.services.map_sources.base import SourceMap, matching, read_json, remember

API_URL = "https://liquipedia.net/warcraft/api.php"

# Seconds between two calls, which the terms set
API_PAUSE = 2.0

# The titles one call of the API takes
TITLES_PER_CALL = 50

_PLAYERS = re.compile(r"Maps \((\d+) Players\)")

# The picture in a map page's infobox: "|image=Wc3AutumnLeaves.png"
_INFOBOX_IMAGE = re.compile(r"\|\s*image\s*=[ \t]*([^\s|}][^\n|}]*)")

_FILE_PREFIX = re.compile(r"^(file|image):", re.IGNORECASE)

# What a player count suggests the map is played as; anything else plays as a free for all
_MODE_BY_PLAYERS = {2: "1v1", 4: "2v2", 6: "3v3", 8: "4v4"}

_last_call = 0.0


def _call(params: dict[str, str]) -> dict[str, Any]:
    """One paced call of the API."""
    # shortcut: paced per process, so two instances can overlap; share the pace if the site complains
    global _last_call
    wait = _last_call + API_PAUSE - monotonic()
    if wait > 0:
        sleep(wait)
    _last_call = monotonic()
    body = read_json(
        API_URL, {"action": "query", "format": "json", "formatversion": "2", **params}
    )
    if not isinstance(body, dict) or "error" in body:
        raise ExternalServiceError("liquipedia.net refused the query")
    return body


def _pages(params: dict[str, str]) -> list[dict[str, Any]]:
    """Every page of a query, past each `continue`; a page split over calls is one."""
    pages: dict[str, dict[str, Any]] = {}
    follow: dict[str, str] = {}
    while True:
        body = _call({**params, **follow})
        for page in (body.get("query") or {}).get("pages") or []:
            whole = pages.setdefault(page.get("title") or "", {})
            for key, value in page.items():
                if isinstance(value, list):
                    whole.setdefault(key, []).extend(value)
                else:
                    whole[key] = value
        follow = body.get("continue") or {}
        if not follow:
            return list(pages.values())


def _row(page: dict[str, Any]) -> SourceMap:
    players = next(
        (
            int(found[1])
            for category in page.get("categories") or []
            if (found := _PLAYERS.search(category.get("title") or ""))
        ),
        None,
    )
    return SourceMap(
        name=page.get("title") or "",
        players=players,
        modes=_MODE_BY_PLAYERS.get(players, "ffa") if players else None,
    )


def _read_rows() -> list[SourceMap]:
    pages = _pages(
        {
            "generator": "categorymembers",
            "gcmtitle": "Category:Maps",
            "gcmtype": "page",
            "gcmlimit": "max",
            "prop": "categories",
            "cllimit": "max",
        }
    )
    return [_row(page) for page in pages if page.get("title")]


def _rows() -> list[SourceMap]:
    return remember("liquipedia", _read_rows)


def _best(name: str, lineage: list[SourceMap]) -> SourceMap:
    """The page of a lineage a name means: its own version, else the last one."""
    version = split_version(name)[1]
    exact = [row for row in lineage if split_version(row.name)[1] == version]
    return max(exact or lineage, key=lambda row: row.name)


def _file_title(name: str) -> str:
    """A file named in an infobox, as the API titles it."""
    bare = _FILE_PREFIX.sub("", name.strip()).replace("_", " ").strip()
    return f"File:{bare[:1].upper()}{bare[1:]}"


def _pictures(titles: list[str]) -> dict[str, str]:
    """Each page's picture url: its infobox names the file, the file's info holds the url."""
    files: dict[str, str] = {}
    for chunk in batched(titles, TITLES_PER_CALL):
        pages = _pages(
            {
                "prop": "revisions",
                "rvprop": "content",
                "rvslots": "main",
                "titles": "|".join(chunk),
            }
        )
        for page in pages:
            revision = (page.get("revisions") or [{}])[0]
            text = ((revision.get("slots") or {}).get("main") or {}).get("content")
            found = _INFOBOX_IMAGE.search(text or "")
            if found:
                files[page.get("title") or ""] = _file_title(found[1])
    urls: dict[str, str] = {}
    for chunk in batched(sorted(set(files.values())), TITLES_PER_CALL):
        # one call and not _pages: a `continue` here only walks a file's older versions
        body = _call({"prop": "imageinfo", "iiprop": "url", "titles": "|".join(chunk)})
        for page in (body.get("query") or {}).get("pages") or []:
            info = page.get("imageinfo") or []
            if info and info[0].get("url"):
                urls[page.get("title") or ""] = info[0]["url"]
    return {title: urls[file] for title, file in files.items() if file in urls}


class Liquipedia:
    key = "liquipedia"
    title = "Liquipedia"
    credit_url = "https://liquipedia.net/warcraft/Portal:Maps"
    license = "CC-BY-SA 3.0"
    # The wiki refuses its files to a page on another site, so a picture shows once it is ours
    copies_pictures = True

    def catalogue(self, q: str) -> list[SourceMap]:
        return matching(_rows(), q)

    def find(self, names: list[str]) -> dict[str, SourceMap]:
        by_base: dict[str, list[SourceMap]] = {}
        for row in _rows():
            by_base.setdefault(folded_base(row.name), []).append(row)
        matched = {
            name: _best(name, by_base[folded_base(name)])
            for name in names
            if folded_base(name) in by_base
        }
        pictures = _pictures(sorted({row.name for row in matched.values()}))
        return {
            name: replace(row, picture_url=pictures.get(row.name))
            for name, row in matched.items()
        }
