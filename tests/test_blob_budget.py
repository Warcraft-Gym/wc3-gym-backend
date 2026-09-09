"""Pin that a binary column never loads with its row.

The database bills every byte it sends, and a picture on a mapped row rides along with every select
of that row. Deferring the column keeps it out of every read that does not serve the image itself.
"""

from sqlalchemy import LargeBinary
from sqlmodel import SQLModel


def _blob_columns() -> list[tuple[str, str, bool]]:
    """Every mapped binary column in the app, with whether it is deferred."""
    found = []
    for mapper in SQLModel._sa_registry.mappers:
        for prop in mapper.column_attrs:
            if isinstance(prop.expression.type, LargeBinary):
                found.append((mapper.class_.__name__, prop.key, bool(prop.deferred)))
    return found


def test_no_picture_is_stored_in_the_database() -> None:
    """The test above passes vacuously now that no column is binary, which is the state to hold:
    a team logo and a map picture are both a URL into Vercel Blob."""
    assert _blob_columns() == []
