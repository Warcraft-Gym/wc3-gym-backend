"""The stage engine columns

The fifth deploy of the events model, and every change is additive. A stage
says whether its bracket plays a third-place series and what its double
elimination final holds: one series, a reset, or none.

A generated bracket series stands on its own, because only a fixture of team
entrants groups series, so `series.match_id` turns nullable. Every series that
exists names its fixture, so the GNL payloads are unchanged.

Revision ID: a7c4f19d0b58
Revises: c6d1a4f80b27
Create Date: 2026-09-13 22:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a7c4f19d0b58"
down_revision: str | Sequence[str] | None = "c6d1a4f80b27"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The series index SQLite rebuilds the table under, dropped and written back
SERIES_INDEX = "uq_series_match_id_player1_id_player2_id"
SERIES_COLUMNS = ("match_id", "player1_id", "player2_id")


def stage_columns() -> list[sa.Column]:
    """The columns a stage gains, both defaulted."""
    return [
        sa.Column(
            "third_place", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column(
            "grand_final_modifier",
            sa.String(length=10),
            nullable=False,
            server_default="one",
        ),
    ]


def upgrade() -> None:
    for column in stage_columns():
        op.add_column("event_stage", column)

    # SQLite drops a NOT NULL only by rebuilding the table, and the rebuild
    # loses the unique index over the three columns, so it is written back
    if op.get_bind().dialect.name == "sqlite":
        op.drop_index(SERIES_INDEX, table_name="series")
        with op.batch_alter_table("series") as batch:
            batch.alter_column("match_id", existing_type=sa.Integer(), nullable=True)
        op.create_index(SERIES_INDEX, "series", list(SERIES_COLUMNS), unique=True)
    else:
        op.alter_column("series", "match_id", existing_type=sa.Integer(), nullable=True)


def downgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        op.drop_index(SERIES_INDEX, table_name="series")
        with op.batch_alter_table("series") as batch:
            batch.alter_column("match_id", existing_type=sa.Integer(), nullable=False)
        op.create_index(SERIES_INDEX, "series", list(SERIES_COLUMNS), unique=True)
    else:
        op.alter_column(
            "series", "match_id", existing_type=sa.Integer(), nullable=False
        )

    for column in stage_columns():
        op.drop_column("event_stage", column.name)
