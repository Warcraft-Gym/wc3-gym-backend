"""The sites the app takes maps from.

An admin lists one source and picks maps from it; the ladder import asks them in
order for a map that is new or has no picture. Adding a site is one module beside
these and one line in SOURCES, and only through an API whose terms allow this use.
"""

import logging

from app.core.exceptions import ExternalServiceError, NotFoundError
from app.services.map_sources.base import MapSource, SourceMap
from app.services.map_sources.liquipedia import Liquipedia
from app.services.map_sources.warcraft3_info import Warcraft3Info

logger = logging.getLogger(__name__)

# In the order an admin's dialog lists them, which opens on the first
SOURCES: dict[str, MapSource] = {
    source.key: source for source in (Liquipedia(), Warcraft3Info())
}

# warcraft3.info first, because it alone holds short names
LADDER_ORDER = ("warcraft3_info", "liquipedia")

# A map, and the source that knew it
type Hit = tuple[MapSource, SourceMap]


def source_of(key: str) -> MapSource:
    source = SOURCES.get(key)
    if source is None:
        raise NotFoundError(f"No map source named {key}")
    return source


def find_in_order(
    names: list[str], order: tuple[str, ...] = LADDER_ORDER
) -> tuple[dict[str, Hit], list[str]]:
    """Each name's map and the source that knew it, and the titles of the sources
    that could not be read. A source is asked only for the names still open."""
    found: dict[str, Hit] = {}
    unreached: list[str] = []
    for key in order:
        left = [name for name in names if name not in found]
        if not left:
            break
        source = SOURCES[key]
        try:
            maps = source.find(left)
        except ExternalServiceError as error:
            logger.warning("Map source %s was not read: %s", source.title, error)
            unreached.append(source.title)
            continue
        found.update({name: (source, row) for name, row in maps.items()})
    return found, unreached
