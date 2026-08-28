"""Add the w3champions ladder matches table and the ladder sync stamp

One row per signed-up player per w3champions 1v1 match, so the ladder page
aggregates stored rows instead of paging w3champions on every view. The
table is new and the column is nullable, so the downgrade drops both.

Revision ID: f8a1c6b3d704
Revises: f7a2c95e3b18
Create Date: 2026-08-28 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "f8a1c6b3d704"
down_revision: str | Sequence[str] | None = "f7a2c95e3b18"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RACES = ("RANDOM", "HU", "OC", "NE", "UD")


def race_type() -> sa.Enum:
    """The race enum. Postgres already holds the type, so it is not created again."""
    if op.get_bind().dialect.name == "postgresql":
        return postgresql.ENUM(*RACES, name="race", create_type=False)
    return sa.Enum(*RACES, name="race")


def upgrade() -> None:
    op.create_table(
        "w3c_ladder_matches",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column(
            "w3c_match_id", sqlmodel.sql.sqltypes.AutoString(length=24), nullable=False
        ),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("wc3_season", sa.Integer(), nullable=False),
        sa.Column("start_time", sa.DateTime(), nullable=False),
        sa.Column("duration_s", sa.Integer(), nullable=False),
        sa.Column(
            "map_name", sqlmodel.sql.sqltypes.AutoString(length=50), nullable=True
        ),
        sa.Column("race", race_type(), nullable=True),
        sa.Column(
            "opp_battletag", sqlmodel.sql.sqltypes.AutoString(length=50), nullable=True
        ),
        sa.Column("opp_race", race_type(), nullable=True),
        sa.Column("won", sa.Boolean(), nullable=False),
        sa.Column("mmr_before", sa.Integer(), nullable=True),
        sa.Column("mmr_after", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_w3c_ladder_matches_user_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_w3c_ladder_matches")),
    )
    op.create_index(
        "uq_w3c_ladder_matches_match_user",
        "w3c_ladder_matches",
        ["w3c_match_id", "user_id"],
        unique=True,
    )
    op.create_index(
        "ix_w3c_ladder_matches_user_id_start_time",
        "w3c_ladder_matches",
        ["user_id", "start_time"],
    )
    op.add_column("users", sa.Column("ladder_synced_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "ladder_synced_at")
    op.drop_index("ix_w3c_ladder_matches_user_id_start_time", "w3c_ladder_matches")
    op.drop_index("uq_w3c_ladder_matches_match_user", "w3c_ladder_matches")
    op.drop_table("w3c_ladder_matches")
