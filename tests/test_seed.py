"""The seed loader rewrites two kinds of CSV cell before COPY takes them.

csv.writer stringified BLOBs as repr(bytes), and MySQL wrote booleans as
0 and 1. Every other cell, NULL as \\N included, goes through untouched.
"""

import pytest

from app.core.seed import blank_secrets, convert


@pytest.mark.parametrize(
    ("cell", "data_type", "expected"),
    [
        ("b'\\x89PNG'", "bytea", r"\x89504e47"),
        ("b''", "bytea", r"\x"),
        (r"\N", "bytea", r"\N"),
        ("0", "boolean", "false"),
        ("1", "boolean", "true"),
        (r"\N", "boolean", r"\N"),
        ("true", "boolean", "true"),
        ("1", "integer", "1"),
        ("0", "text", "0"),
        ("Grubby", "character varying", "Grubby"),
        (r"\N", "timestamp with time zone", r"\N"),
    ],
)
def test_convert(cell: str, data_type: str, expected: str) -> None:
    assert convert(cell, data_type) == expected


def test_the_export_blanks_the_secret_settings_and_nothing_else() -> None:
    header = ["id", "key", "value", "description"]
    assert blank_secrets(
        "settings", header, ["1", "KOTH_NIGHTBOT_TOKEN", "abc", "d"]
    ) == ["1", "KOTH_NIGHTBOT_TOKEN", "", "d"]
    assert blank_secrets("settings", header, ["2", "current_season", "18", "d"]) == [
        "2",
        "current_season",
        "18",
        "d",
    ]
    assert blank_secrets(
        "users", ["id", "key", "value"], ["1", "KOTH_NIGHTBOT_TOKEN", "x"]
    ) == ["1", "KOTH_NIGHTBOT_TOKEN", "x"]
