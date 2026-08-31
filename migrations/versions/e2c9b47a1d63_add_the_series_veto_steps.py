"""Add the series veto steps

A series keeps the ordered steps of its map veto: which side took which map,
and whether the step banned or picked it. The order itself stays on the
season, in pick_ban, so a row carries only what the players chose.

Revision ID: e2c9b47a1d63
Revises: b8d3f6a20c71
Create Date: 2026-08-31 16:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e2c9b47a1d63"
down_revision: str | Sequence[str] | None = "b8d3f6a20c71"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

VETO_STEP = "series_veto_step"


def upgrade() -> None:
    op.create_table(
        VETO_STEP,
        sa.Column("series_id", sa.Integer(), nullable=False),
        sa.Column("step_no", sa.Integer(), nullable=False),
        sa.Column("side", sa.String(length=1), nullable=False),
        sa.Column("action", sa.String(length=4), nullable=False),
        sa.Column("map_id", sa.Integer(), nullable=False),
        sa.ForeignKeyConstraint(
            ["map_id"], ["maps.id"], name=op.f("fk_series_veto_step_map_id_maps")
        ),
        sa.ForeignKeyConstraint(
            ["series_id"],
            ["series.id"],
            name=op.f("fk_series_veto_step_series_id_series"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "series_id", "step_no", name=op.f("pk_series_veto_step")
        ),
    )


def downgrade() -> None:
    op.drop_table(VETO_STEP)
