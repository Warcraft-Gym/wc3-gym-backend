"""The seed loader rewrites two kinds of CSV cell before COPY takes them.

csv.writer stringified BLOBs as repr(bytes), and MySQL wrote booleans as
0 and 1. Every other cell, NULL as \\N included, goes through untouched.
"""

import pytest

from app.core.seed import convert


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


def test_seed_prices_are_the_wc3no_rows() -> None:
    """A seeded season pays what production S17 and S18 pay, not the S19 catalogue."""
    from app.core import seed
    from app.core.achievements import WC3NO, WC3NO_PAID

    assert "WC3NO_PAID" in seed.__dict__ and "DEFAULT_PAID" not in seed.__dict__
    assert set(WC3NO_PAID) == {rule.id for rule in WC3NO}
    assert (WC3NO_PAID["ladder_goal"], WC3NO_PAID["win_first"]) == (500, 15)
