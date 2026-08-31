"""The 1v1 maps w3champions runs, matched to what warcraft3.info knows.

w3champions names the maps of the ladder and warcraft3.info holds the short
name and the picture of every map ever published, so the import reads both
and pairs them. The pairing is by name and version: warcraft3.info keeps the
old versions of a map under their own names, so "Autumn Leaves v2" belongs to
"Autumn Leaves 2.0" and not to the older "Autumn Leaves".
"""

import logging
import re

import requests

from app.models.map import LadderMapRow
from app.services.w3c import REQUEST_TIMEOUT, W3CService

logger = logging.getLogger(__name__)

# Every map warcraft3.info knows, with its short name and its picture.
MAP_DB_URL = "https://warcraft3.info/api/v1/maps"

# Where warcraft3.info serves the pictures it names.
IMAGE_BASE_URL = "https://d3upx5peno0o6w.cloudfront.net/"

# The w3champions game mode the league plays.
SOLO_MODE = 1

# A trailing version word: "v2", "2.0", "v1.3".
_VERSION = re.compile(r"^v?(\d+(?:\.\d+)*)$")

# The version in a map file path: "44_w3c_260615_2308_AutumnLeaves_v2.0.w3x".
_PATH_VERSION = re.compile(r"[_-]v(\d+(?:\.\d+)*)")

# A warcraft3.info map, keyed by the base name it was published under.
type MapIndex = dict[str, list[tuple[str | None, dict]]]


def _normalize(name: str) -> str:
    """Lower case, where anything but a letter, a digit or a dot is a space."""
    return re.sub(r"[^a-z0-9.]+", " ", name.lower()).strip()


def _canonical(version: str) -> str:
    """The same version however it is written: "v2", "2" and "2.0" are one."""
    while "." in version and version.endswith("0"):
        version = version[:-1].rstrip(".")
    return version


def _split_version(name: str) -> tuple[str, str | None]:
    """The name without its trailing version word, and that version."""
    words = _normalize(name).split()
    found = _VERSION.match(words[-1]) if words else None
    if found:
        return " ".join(words[:-1]), _canonical(found[1])
    return " ".join(words), None


def _path_version(path: str) -> str | None:
    """The version in the file name, which a display name may leave out."""
    found = _PATH_VERSION.search(path)
    return _canonical(found[1]) if found else None


def _newest_file(entry: dict) -> str:
    """When warcraft3.info last saw a file of this map."""
    return max(
        (file.get("updated_at") or "" for file in entry.get("map_files") or []),
        default="",
    )


def folded_base(name: str) -> str:
    """The name folded to its lineage: case, spacing and the version word dropped."""
    return _split_version(name)[0].replace(" ", "")


def initials(name: str) -> str:
    """The short name a map falls back to: the initials of its base name."""
    base = _split_version(name)[0]
    return "".join(word[0] for word in base.split()).upper() or "MAP"


def free_shortname(preferred: str | None, name: str, taken: set[str]) -> str:
    """A short name no other map holds: the matched one, else the initials."""
    if preferred and preferred.lower() not in taken:
        return preferred
    base = initials(name)
    shortname, suffix = base, 2
    while shortname.lower() in taken:
        shortname, suffix = f"{base}{suffix}", suffix + 1
    return shortname


def _match(ladder_map: dict, by_base: MapIndex) -> dict | None:
    """The warcraft3.info map behind a ladder map, by base name and version."""
    base, version = _split_version(ladder_map.get("name") or "")
    if version is None:
        version = _path_version(ladder_map.get("path") or "")
    candidates = by_base.get(base) or []
    exact = [entry for entry_version, entry in candidates if entry_version == version]
    # With no version to go by, the map published last is the one meant
    return max(
        exact or [entry for _, entry in candidates], key=_newest_file, default=None
    )


def _row(ladder_map: dict, by_base: MapIndex) -> LadderMapRow:
    """One ladder map, and the short name and picture matched to it."""
    name = ladder_map.get("name") or ""
    entry = _match(ladder_map, by_base)
    if entry is None:
        return LadderMapRow(w3c_name=name, status="no_match")
    file_name = (entry.get("image") or {}).get("file_name")
    return LadderMapRow(
        w3c_name=name,
        matched_name=entry.get("name"),
        shortname=entry.get("short"),
        image_url=f"{IMAGE_BASE_URL}{file_name}" if file_name else None,
    )


def ladder_maps() -> list[LadderMapRow]:
    """Every 1v1 ladder map, with the short name and picture matched to it."""
    w3c = W3CService()
    modes = w3c.send_request(url=f"{w3c.base_url()}/ladder/active-modes") or []
    maps = next(
        (mode.get("maps") or [] for mode in modes if mode.get("id") == SOLO_MODE), []
    )
    by_base: MapIndex = {}
    for entry in w3c.send_request(url=MAP_DB_URL) or []:
        base, version = _split_version(entry.get("name") or "")
        by_base.setdefault(base, []).append((version, entry))
    return [_row(ladder_map, by_base) for ladder_map in maps]


def fetch_image(url: str) -> bytes | None:
    """The picture behind the url. A picture that does not answer is skipped."""
    try:
        response = requests.get(url, timeout=REQUEST_TIMEOUT)
    except requests.exceptions.RequestException as failure:
        logger.warning("map picture %s: %s", url, failure)
        return None
    return response.content if response.status_code == 200 else None
