"""The migrations and the models must describe the same schema.

Without this, a column added to a model would reach production only
through create_all, which no longer runs, so the table would be missing
the column instead.
"""

from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine
from sqlmodel import SQLModel

from tests.migrate import upgrade_to_head
from tests.test_models import import_all_models


def test_a_migrated_database_matches_the_models(tmp_path):
    import_all_models()
    db_file = tmp_path / "migrated.sqlite"
    upgrade_to_head(f"sqlite:///{db_file}")

    engine = create_engine(f"sqlite:///{db_file}")
    with engine.connect() as connection:
        context = MigrationContext.configure(connection)
        differences = compare_metadata(context, SQLModel.metadata)

    assert differences == []
