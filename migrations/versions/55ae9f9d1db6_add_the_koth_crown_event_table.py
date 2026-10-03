"""Add the KOTH crown event table

A crown change of a KOTH bracket that no result shows: a crown passed or
emptied by hand, or emptied by a rule. Each row sits after the series whose
sequence it names, so the walk of a bracket's results crowns from it.

Revision ID: 55ae9f9d1db6
Revises: c9e2a4d61b07
Create Date: 2026-10-04 01:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "55ae9f9d1db6"
down_revision: str | Sequence[str] | None = "c9e2a4d61b07"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "koth_crown_event",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("division_id", sa.Integer(), nullable=False),
        sa.Column("after_sequence", sa.Integer(), nullable=False),
        sa.Column("entrant_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["division_id"], ["event_division.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["entrant_id"], ["event_entrant.id"], ondelete="SET NULL"
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_koth_crown_event_division_id", "koth_crown_event", ["division_id"]
    )


def downgrade() -> None:
    op.drop_table("koth_crown_event")
