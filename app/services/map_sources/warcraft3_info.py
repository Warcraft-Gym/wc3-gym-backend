"""warcraft3.info: the short name and the picture of every map ever published.

It keeps the old versions of a map under their own names, so a match by name
alone picks the stale one: "Autumn Leaves v2" belongs to "Autumn Leaves 2.0" and
not to the older "Autumn Leaves". The version decides.
"""

from app.models.types import MAP_MODES, map_modes
from app.services.ladder_maps import split_version
from app.services.map_sources.base import SourceMap, matching, read_json, remember

# Every map warcraft3.info knows, with its short name and its picture.
MAP_DB_URL = "https://warcraft3.info/api/v1/maps"

# Where warcraft3.info serves the pictures it names.
IMAGE_BASE_URL = "https://d3upx5peno0o6w.cloudfront.net/"

# A warcraft3.info map, keyed by the base name it was published under.
type MapIndex = dict[str, list[tuple[str | None, dict]]]


def _entries() -> list[dict]:
    return remember("warcraft3_info", lambda: read_json(MAP_DB_URL) or [])


def _files(entry: dict) -> int:
    """How many files warcraft3.info holds of this map."""
    return entry.get("map_files_count") or 0


def _modes(entry: dict) -> str | None:
    """The modes a map is tagged with in the app's words: "1vs1" reads "1v1"."""
    tags = {
        (tag.get("mode") or "").lower().replace("vs", "v")
        for tag in entry.get("tags") or []
    }
    return map_modes(sorted(tags & set(MAP_MODES)))


def _row(entry: dict) -> SourceMap:
    file_name = (entry.get("image") or {}).get("file_name")
    return SourceMap(
        name=entry.get("name") or "",
        modes=_modes(entry),
        shortname=entry.get("short"),
        picture_url=f"{IMAGE_BASE_URL}{file_name}" if file_name else None,
    )


def _index(entries: list[dict]) -> MapIndex:
    by_base: MapIndex = {}
    for entry in entries:
        base, version = split_version(entry.get("name") or "")
        by_base.setdefault(base, []).append((version, entry))
    return by_base


def _match(name: str, by_base: MapIndex) -> dict | None:
    """The map behind a name, by base name and version."""
    base, version = split_version(name)
    candidates = by_base.get(base) or []
    exact = [entry for entry_version, entry in candidates if entry_version == version]
    # With no version to go by, the one with the most files is the one the ladder runs
    return max(exact or [entry for _, entry in candidates], key=_files, default=None)


class Warcraft3Info:
    key = "warcraft3_info"
    title = "warcraft3.info"
    credit_url = "https://warcraft3.info/maps"
    license = None
    # Its pictures are already on a CDN and cost us nothing where they are
    copies_pictures = False

    def catalogue(self, q: str) -> list[SourceMap]:
        return matching([_row(entry) for entry in _entries()], q)

    def find(self, names: list[str]) -> dict[str, SourceMap]:
        by_base = _index(_entries())
        matches = {name: _match(name, by_base) for name in names}
        return {name: _row(entry) for name, entry in matches.items() if entry}
