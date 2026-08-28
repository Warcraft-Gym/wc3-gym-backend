"""Add the ladder achievements table and seed every season with the wc3.no set

An achievement rule is code; a row here is one season's instance of it, with
the points that season pays. Seeding every existing season with the same 24
rules at their current prices leaves every published number unchanged, which
the wc3.no oracle checks.

The seed values are written out here rather than imported from
app.core.achievements, so this migration keeps saying what it did even after
the catalogue in the code changes.

Revision ID: a3d92f7c04be
Revises: c5b8e0a41d67
Create Date: 2026-08-28 18:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a3d92f7c04be"
down_revision: str | None = "c5b8e0a41d67"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# (rule id, points) as the catalogue prices them today.
SEED = [
    ("ladder_goal", 500),
    ("double_up", 1000),
    ("i_am_the_captain_now", 100),
    ("addicted", 100),
    ("elite", 100),
    ("dats_fakt_ap", 50),
    ("winner_winner", 50),
    ("sad_trombone", 50),
    ("win_streak_2", 50),
    ("win_first", 15),
    ("lose_first", 25),
    ("win_streak", 25),
    ("win_every_map", 25),
    ("rising_star", 25),
    ("falling_star", 25),
    ("duck_hunting", 10),
    ("night_elf", 10),
    ("undead", 10),
    ("orc", 10),
    ("human", 10),
    ("join_them", 10),
    ("winter", 10),
    ("holiday", 5),
    ("newbie", 5),
]


def upgrade() -> None:
    table = op.create_table(
        "ladder_achievements",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("season_id", sa.Integer(), nullable=True),
        sa.Column(
            "rule_id", sqlmodel.sql.sqltypes.AutoString(length=40), nullable=False
        ),
        sa.Column("points", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(["season_id"], ["seasons.id"]),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "uq_ladder_achievements_season_rule",
        "ladder_achievements",
        ["season_id", "rule_id"],
        unique=True,
    )
    # Both engines count NULLs as distinct, so the lifetime rows say it here
    op.create_index(
        "uq_ladder_achievements_lifetime_rule",
        "ladder_achievements",
        ["rule_id"],
        unique=True,
        sqlite_where=sa.text("season_id IS NULL"),
        postgresql_where=sa.text("season_id IS NULL"),
    )

    seasons = op.get_bind().execute(sa.text("SELECT id FROM seasons")).scalars().all()
    if seasons:
        op.bulk_insert(
            table,
            [
                {"season_id": season_id, "rule_id": rule_id, "points": points}
                for season_id in seasons
                for rule_id, points in SEED
            ],
        )


def downgrade() -> None:
    op.drop_index("uq_ladder_achievements_lifetime_rule", "ladder_achievements")
    op.drop_index("uq_ladder_achievements_season_rule", "ladder_achievements")
    op.drop_table("ladder_achievements")
