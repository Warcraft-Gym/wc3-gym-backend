"""Add the per-week player availability

One row per player, season and week, saying whether he can play it. No row is
no answer, and no answer counts as available, so the table holds only the weeks
somebody answered for. The player and his captain write the same row, and
set_by_user_id names whoever wrote it last.

Revision ID: d8c1f4a70b39
Revises: f1a6c8d3b204
Create Date: 2026-08-31 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d8c1f4a70b39"
down_revision: str | Sequence[str] | None = "f1a6c8d3b204"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "user_season_availability"
INDEX = "ix_user_season_availability_season_id"


def upgrade() -> None:
    op.create_table(
        TABLE,
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("season_id", sa.Integer(), nullable=False),
        sa.Column("playday", sa.Integer(), nullable=False),
        sa.Column("available", sa.Boolean(), nullable=False),
        sa.Column("set_by_user_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["season_id"],
            ["seasons.id"],
            name=op.f("fk_user_season_availability_season_id_seasons"),
        ),
        sa.ForeignKeyConstraint(
            ["set_by_user_id"],
            ["users.id"],
            name=op.f("fk_user_season_availability_set_by_user_id_users"),
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_user_season_availability_user_id_users"),
        ),
        sa.PrimaryKeyConstraint(
            "user_id", "season_id", "playday", name=op.f("pk_user_season_availability")
        ),
    )
    op.create_index(op.f(INDEX), TABLE, ["season_id"], unique=False)


def downgrade() -> None:
    op.drop_index(op.f(INDEX), table_name=TABLE)
    op.drop_table(TABLE)
