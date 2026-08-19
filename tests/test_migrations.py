"""The migrations and the models must describe the same schema.

`alembic upgrade head` is the only thing that builds the schema, so a column added to
a model without a migration is missing from the table in production.
"""

from pathlib import Path

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import create_engine, text
from sqlmodel import SQLModel

from tests.migrate import upgrade_to, upgrade_to_head
from tests.test_models import import_all_models

# The revision before the seasons table carries a score system
BEFORE_SCORE_SYSTEM = "658616cf0c2b"


def test_a_migrated_database_matches_the_models(tmp_path: Path) -> None:
    import_all_models()
    db_file = tmp_path / "migrated.sqlite"
    upgrade_to_head(f"sqlite:///{db_file}")

    engine = create_engine(f"sqlite:///{db_file}")
    with engine.connect() as connection:
        context = MigrationContext.configure(connection)
        differences = compare_metadata(context, SQLModel.metadata)

    assert differences == []


@pytest.mark.parametrize(
    "setting,expected",
    [
        ("helpstone", "helpstone"),
        ("standard", "standard"),
        (None, "standard"),  # no setting row, so the column default holds
    ],
)
def test_the_score_system_backfill_reads_the_settings_row(
    tmp_path: Path, setting: str | None, expected: str
) -> None:
    db_file = tmp_path / "backfill.sqlite"
    url = f"sqlite:///{db_file}"
    upgrade_to(url, BEFORE_SCORE_SYSTEM)

    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO seasons (name, number_weeks, series_per_week) "
                "VALUES ('Season 1', 4, 2)"
            )
        )
        if setting is not None:
            connection.execute(
                text("INSERT INTO settings (key, value) VALUES ('score_system', :v)"),
                {"v": setting},
            )

    upgrade_to(url, "head")

    with engine.connect() as connection:
        assert connection.scalars(text("SELECT score_system FROM seasons")).all() == [
            expected
        ]
