"""The maps w3champions runs, and how a map's name reads.

w3champions names the maps of the ladder and nothing more; a short name and a
picture come from the map sources (app.services.map_sources). A name carries its
version, or the map's file path does: "Last Refuge" runs "4_LastRefuge_v1.5.w3x".
"""

import re

from app.services.w3c import W3CService

# The w3champions game mode the league plays.
SOLO_MODE = 1
# The W3Champions game modes a pool is read from, by the mode a map is tagged with
MODE_NAMES = {1: "1v1", 2: "2v2", 4: "4v4"}

# A trailing version word: "v2", "2.0", "v1.3".
_VERSION = re.compile(r"^v?(\d+(?:\.\d+)*)$")

# The version in a map file path: "44_w3c_260615_2308_AutumnLeaves_v2.0.w3x".
_PATH_VERSION = re.compile(r"[_-]v(\d+(?:\.\d+)*)")


def _normalize(name: str) -> str:
    """Lower case, where anything but a letter, a digit or a dot is a space."""
    return re.sub(r"[^a-z0-9.]+", " ", name.lower()).strip()


def _canonical(version: str) -> str:
    """The same version however it is written: "v2", "2" and "2.0" are one."""
    while "." in version and version.endswith("0"):
        version = version[:-1].rstrip(".")
    return version


def split_version(name: str) -> tuple[str, str | None]:
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


def folded_base(name: str) -> str:
    """The name folded to its lineage: case, spacing and the version word dropped."""
    return split_version(name)[0].replace(" ", "")


def initials(name: str) -> str:
    """The short name a map falls back to: the initials of its base name."""
    base = split_version(name)[0]
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


def _versioned(ladder_map: dict) -> str:
    """A ladder map's name, with its file's version when the name leaves it out."""
    name = ladder_map.get("name") or ""
    version = _path_version(ladder_map.get("path") or "")
    if version and split_version(name)[1] is None:
        return f"{name} v{version}"
    return name


def ladder_names(mode: int = SOLO_MODE) -> dict[str, str]:
    """Every map of one W3Champions game mode, the 1v1 one unless named: its name,
    and the name a source is asked for, which carries its version."""
    w3c = W3CService()
    modes = w3c.send_request(url=f"{w3c.base_url()}/ladder/active-modes") or []
    maps = next(
        (
            mode_row.get("maps") or []
            for mode_row in modes
            if mode_row.get("id") == mode
        ),
        [],
    )
    return {ladder_map.get("name") or "": _versioned(ladder_map) for ladder_map in maps}
