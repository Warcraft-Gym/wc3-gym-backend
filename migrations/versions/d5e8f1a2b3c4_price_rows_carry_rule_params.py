"""Price rows carry rule params

A season's price row overrides the numbers its rule reads, so an admin
sets a threshold per season without a code change.

Revision ID: d5e8f1a2b3c4
Revises: d5e0f3a8b2c4
Create Date: 2026-09-07 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d5e8f1a2b3c4"
down_revision: str | Sequence[str] | None = "d5e0f3a8b2c4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "ladder_achievements",
        sa.Column("params", sa.JSON(), nullable=False, server_default="{}"),
    )


def downgrade() -> None:
    op.drop_column("ladder_achievements", "params")
