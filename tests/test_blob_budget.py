"""Pin that a binary column never loads with its row.

A team logo is ~44 KB, so a select of every team carrying its icon reads 890 KB where the answer is
2 KB, and a season of series reads 21 MB where the answer is 190 KB. The database bills those bytes.
Deferring the column is what keeps them out of every read that does not serve the image itself.
"""

from sqlalchemy import LargeBinary, inspect
from sqlmodel import SQLModel

from app.models.team import Team


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


def test_the_team_logo_is_a_binary_column() -> None:
    """The test above passes vacuously if the icon stops being binary, so pin that it is one."""
    assert ("Team", "icon", True) in _blob_columns()
    assert inspect(Team).get_property("icon").deferred
