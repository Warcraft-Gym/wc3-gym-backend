"""Pin that a binary column never loads with its row.

The database bills every byte it sends, and a picture on a mapped row rides along with every select
of that row. Deferring the column keeps it out of every read that does not serve the image itself.
"""

from sqlalchemy import LargeBinary, inspect
from sqlmodel import SQLModel

from app.models.map import Map


def _blob_columns() -> list[tuple[str, str, bool]]:
    """Every mapped binary column in the app, with whether it is deferred."""
    found = []
    for mapper in SQLModel._sa_registry.mappers:
        for prop in mapper.column_attrs:
            if isinstance(prop.expression.type, LargeBinary):
                found.append((mapper.class_.__name__, prop.key, bool(prop.deferred)))
    return found


def test_every_binary_column_is_deferred() -> None:
    loaded = [f"{cls}.{key}" for cls, key, deferred in _blob_columns() if not deferred]
    assert not loaded, (
        f"these load with their row and bill the bytes on every read: {loaded}"
    )


def test_the_map_picture_is_a_binary_column() -> None:
    """The test above passes vacuously once no column is binary, so pin that this one still is."""
    assert ("Map", "icon", True) in _blob_columns()
    assert inspect(Map).get_property("icon").deferred
