"""The migrations and the models must describe the same schema.

`alembic upgrade head` is the only thing that builds the schema, so a column added to
a model without a migration is missing from the table in production.
"""

from pathlib import Path

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import Column, Index, column, create_engine, table, text
from sqlmodel import SQLModel

from tests.migrate import downgrade_to, fresh_database, upgrade_to, upgrade_to_head
from tests.test_models import import_all_models

# The revision before the seasons table carries a score system
BEFORE_SCORE_SYSTEM = "658616cf0c2b"
# The revision before the w3c stats are unique per user, race and season
BEFORE_W3C_STATS_UNIQUE = "9f4b7c1d2ae5"
# The revision before the captains of a team season are their own rows
BEFORE_CAPTAIN_TABLE = "5f4a1a4d88d3"
# The revision before every app-owned Discord role is a binding row
BEFORE_ROLE_BINDINGS = "b3f9d7c21a48"
# The revision before the season setting is spelled w3c
BEFORE_W3C_SEASON_KEY = "5f4a1a4d88d3"


def comparable(
    obj: object, name: str | None, type_: str, reflected: bool, compare_to: object
) -> bool:
    """Whether autogenerate can tell this object apart from the database.

    An index over an expression reads back as text no dialect turns into the
    element the model holds, so alembic reports it as changed on every run.
    The natural keys are checked by the writes they refuse instead, in
    tests/test_natural_keys.py.
    """
    if isinstance(obj, Index):
        return all(isinstance(part, Column) for part in obj.expressions)
    return True


def test_a_migrated_database_matches_the_models(tmp_path: Path) -> None:
    import_all_models()
    url = fresh_database(tmp_path, "migrated")
    upgrade_to_head(url)

    engine = create_engine(url)
    with engine.connect() as connection:
        context = MigrationContext.configure(
            connection, opts={"include_object": comparable}
        )
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
    url = fresh_database(tmp_path, "backfill")
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
    url = fresh_database(tmp_path, "dedupe")
    upgrade_to(url, BEFORE_W3C_STATS_UNIQUE)

    engine = create_engine(url)
    with engine.begin() as connection:
        # A table construct, not text: Postgres needs the camelCase names quoted
        users = table(
            "users",
            *(
                column(c)
                for c in ("id", "name", "battleTag", "discordTag", "discordId", "race")
            ),
        )
        connection.execute(
            users.insert().values(
                id=1,
                name="P1",
                battleTag="P1#1111",
                discordTag="p1",
                discordId="1",
                race="HU",
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


def test_the_migrations_have_one_head() -> None:
    """Two heads mean two branches each added a migration and neither rebased; upgrade refuses that."""
    from alembic.config import Config
    from alembic.script import ScriptDirectory

    assert len(ScriptDirectory.from_config(Config("alembic.ini")).get_heads()) == 1


def test_the_captain_slots_move_into_the_table_and_back(tmp_path: Path) -> None:
    """Three filled slots become three rows; a downgrade keeps the first three."""
    url = fresh_database(tmp_path, "captains")
    upgrade_to(url, BEFORE_CAPTAIN_TABLE)

    engine = create_engine(url)
    users = table(
        "users",
        *(
            column(c)
            for c in ("id", "name", "battleTag", "discordTag", "discordId", "race")
        ),
    )
    with engine.begin() as connection:
        for user_id in (1, 2, 3, 4):
            connection.execute(
                users.insert().values(
                    id=user_id,
                    name=f"P{user_id}",
                    battleTag=f"P{user_id}#111{user_id}",
                    discordTag=f"p{user_id}",
                    discordId=str(user_id),
                    race="HU",
                )
            )
        connection.execute(
            text(
                "INSERT INTO seasons (id, name, number_weeks, series_per_week) "
                "VALUES (1, 'Season 1', 4, 2)"
            )
        )
        connection.execute(text("INSERT INTO teams (id, name) VALUES (1, 'Alpha')"))
        connection.execute(
            text(
                "INSERT INTO team_season (team_id, season_id, coach_1_id, coach_2_id, "
                "coach_3_id) VALUES (1, 1, 3, 1, 3)"
            )
        )

    upgrade_to(url, "head")
    with engine.begin() as connection:
        # A user in two slots is one captain
        assert connection.execute(
            text("SELECT user_id FROM team_season_captain ORDER BY user_id")
        ).all() == [(1,), (3,)]
        connection.execute(
            text(
                "INSERT INTO team_season_captain (team_id, season_id, user_id) "
                "VALUES (1, 1, 2), (1, 1, 4)"
            )
        )

    downgrade_to(url, BEFORE_CAPTAIN_TABLE)
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT coach_1_id, coach_2_id, coach_3_id FROM team_season")
        ).all() == [(1, 2, 3)]


def test_the_team_roles_and_the_captain_role_become_bindings(tmp_path: Path) -> None:
    """The column and the settings row seed the table; the downgrade puts the
    team roles back in the column."""
    url = fresh_database(tmp_path, "bindings")
    upgrade_to(url, BEFORE_ROLE_BINDINGS)

    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO teams (id, name, discord_role) VALUES (1, 'Alpha', '7788')"
            )
        )
        connection.execute(text("INSERT INTO teams (id, name) VALUES (2, 'Beta')"))
        connection.execute(
            text(
                "INSERT INTO settings (key, value) "
                "VALUES ('captain_coach_role', 'coach-role')"
            )
        )

    upgrade_to(url, "head")
    with engine.connect() as connection:
        assert connection.execute(
            text(
                "SELECT kind, team_id, discord_role FROM discord_role_binding ORDER BY id"
            )
        ).all() == [("captain", None, "coach-role"), ("team", 1, "7788")]

    downgrade_to(url, BEFORE_ROLE_BINDINGS)
    with engine.connect() as connection:
        assert connection.execute(
            text("SELECT id, discord_role FROM teams ORDER BY id")
        ).all() == [(1, "7788"), (2, None)]


def test_the_w3c_season_setting_is_renamed_and_renamed_back(tmp_path: Path) -> None:
    """The pinned row keeps its value; only the key is spelled w3c."""
    url = fresh_database(tmp_path, "season_key")
    upgrade_to(url, BEFORE_W3C_SEASON_KEY)

    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO settings (key, value) VALUES ('current_wc3_season', '21')"
            )
        )

    upgrade_to(url, "head")
    with engine.connect() as connection:
        assert connection.execute(text("SELECT key, value FROM settings")).all() == [
            ("current_w3c_season", "21")
        ]

    downgrade_to(url, BEFORE_W3C_SEASON_KEY)
    with engine.connect() as connection:
        assert connection.execute(text("SELECT key, value FROM settings")).all() == [
            ("current_wc3_season", "21")
        ]
