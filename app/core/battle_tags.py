"""Which battle tags and Discord ids name a real account.

The importers write stand-ins where a sheet had no value: a `Name#GNLnn`,
`Fantasy_User#` or `Review#` battle tag. A stand-in gets no user_battle_tag
row. Migration e07324d2b4f9 holds a frozen copy of this rule, and
tests/test_battle_tags.py pins the two to each other.
"""

import re

# Real = Name#digits; #GNLnn, Fantasy_User# and Review# are importer stand-ins
REAL_TAG = re.compile(r"[^#\s]+#\d+")
STAND_IN_PREFIXES = ("fantasy_user#", "review#")
# The prefix of the history import's stand-in Discord id; the import writes null now
STAND_IN_ID_PREFIX = "gnl-"


def fold(tag: str) -> str:
    """The key a tag matches on: trimmed and lower case."""
    return tag.strip().lower()


def is_real_tag(tag: str | None) -> bool:
    """A tag W3Champions could know: Name#digits, and not a stand-in."""
    text = (tag or "").strip()
    return bool(REAL_TAG.fullmatch(text)) and not text.lower().startswith(
        STAND_IN_PREFIXES
    )


def has_login(discord_id: str | None) -> bool:
    """A Discord id someone logged in with: not blank and not a gnl- stand-in."""
    text = (discord_id or "").strip()
    return bool(text) and not text.startswith(STAND_IN_ID_PREFIX)
