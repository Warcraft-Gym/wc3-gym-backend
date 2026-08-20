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
# The revision before the w3c stats are unique per user, race and season
BEFORE_W3C_STATS_UNIQUE = "9f4b7c1d2ae5"


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


def test_the_w3c_stats_dedupe_keeps_the_highest_id_of_each_key(tmp_path: Path) -> None:
    """The highest id is the row the last sync wrote, so it is the one to
    keep. A null race is one key, not one key per row."""
    db_file = tmp_path / "dedupe.sqlite"
    url = f"sqlite:///{db_file}"
    upgrade_to(url, BEFORE_W3C_STATS_UNIQUE)

    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO users (id, name, battleTag, discordTag, discordId, race) "
                "VALUES (1, 'P1', 'P1#1111', 'p1', '1', 'HU')"
            )
        )
        # id, user, race, season, mmr. Rows 1 to 3 share one key, and so do 5 and 6.
        for row in [
            (1, 1, "HU", 21, 1500),
            (2, 1, "HU", 21, 1600),
            (3, 1, "HU", 21, 1700),
            (4, 1, "OC", 21, 1400),
            (5, 1, None, 21, 1200),
            (6, 1, None, 21, 1300),
            (7, 1, "HU", 20, 1100),
        ]:
            connection.execute(
                text(
                    "INSERT INTO w3cstats (id, user_id, race, wc3_season, mmr) "
                    "VALUES (:id, :user_id, :race, :season, :mmr)"
                ),
                dict(zip(["id", "user_id", "race", "season", "mmr"], row, strict=True)),
            )

    upgrade_to(url, "head")

    with engine.connect() as connection:
        kept = connection.execute(
            text("SELECT id, mmr FROM w3cstats ORDER BY id")
        ).all()
    assert kept == [(3, 1700), (4, 1400), (6, 1300), (7, 1100)]
