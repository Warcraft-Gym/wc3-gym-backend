"""What every map source shares: the row it answers, its contract, and its reads.

A source reads through `read` so that every site sees the same User-Agent, which
names the app and where to reach its maintainers. Never a browser's.
"""

from collections.abc import Callable
from dataclasses import dataclass
from time import monotonic
from typing import Any, Protocol
from urllib.parse import urlsplit

import requests

from app.core.exceptions import ExternalServiceError

# Who reads, and where to reach the maintainers: the public repository
USER_AGENT = "wc3-gym-backend (+https://github.com/Warcraft-Gym/wc3-gym-backend)"

# Seconds a source's read can hold the thread before it fails
REQUEST_TIMEOUT = 10

# The rows a list of a source's maps answers at most, above what the sites hold today so that a
# page can filter a whole list
CATALOGUE_ROWS = 500

# How long a process keeps a source's whole list
CACHE_SECONDS = 86_400

# One connection pool for every source
_session = requests.Session()
_session.headers["User-Agent"] = USER_AGENT

_cache: dict[str, tuple[float, Any]] = {}


@dataclass
class SourceMap:
    """One map as a source knows it. `modes` is a suggestion, as "1v1,2v2"."""

    name: str
    players: int | None = None
    modes: str | None = None
    shortname: str | None = None
    picture_url: str | None = None


class MapSource(Protocol):
    """A site the app takes maps from. One module and one line in SOURCES add a site."""

    key: str
    title: str
    credit_url: str
    license: str | None
    # Whether a picture is copied into our store, or kept at the url it is published at
    copies_pictures: bool

    def catalogue(self, q: str) -> list[SourceMap]:
        """At most CATALOGUE_ROWS maps matching the search; "" lists from the start.
        A page shows a row's picture straight from the site, so a site that refuses that
        lists none."""
        ...

    def find(self, names: list[str]) -> dict[str, SourceMap]:
        """The source's best match per name it knows, with its picture. Raises
        ExternalServiceError when the site cannot be read."""
        ...


def read(url: str, params: dict[str, str] | None = None) -> requests.Response:
    """One read of a source. Anything but a 200 is a failure, named by its status alone."""
    host = urlsplit(url).hostname
    try:
        response = _session.get(url, params=params, timeout=REQUEST_TIMEOUT)
    except requests.RequestException as error:
        raise ExternalServiceError(f"{host} could not be reached: {error!s}")
    if response.status_code != 200:
        raise ExternalServiceError(f"{host} answered {response.status_code}")
    return response


def read_json(url: str, params: dict[str, str] | None = None) -> Any:  # noqa: ANN401  # a source's body has no fixed shape
    """One read of a source's API."""
    response = read(url, params)
    try:
        return response.json()
    except ValueError:
        raise ExternalServiceError(f"{urlsplit(url).hostname} did not answer JSON")


def remember[T](key: str, load: Callable[[], T]) -> T:
    """A source's whole list, read once per process and day."""
    # shortcut: per-process cache, so each serverless instance reads once; share it if a site complains
    cached = _cache.get(key)
    if cached and cached[0] > monotonic():
        return cached[1]
    value = load()
    _cache[key] = (monotonic() + CACHE_SECONDS, value)
    return value


def matching(rows: list[SourceMap], q: str) -> list[SourceMap]:
    """The rows of a list held in memory whose name holds the search, by name."""
    wanted = q.strip().lower()
    hits = [row for row in rows if wanted in row.name.lower()]
    return sorted(hits, key=lambda row: row.name.lower())[:CATALOGUE_ROWS]
