"""Add the season ladder sync stamp

`users.ladder_synced_at` says when one player was last asked for, so a
season that was never synced reads as synced off another season's run. The
season sync stamps this column when its last chunk has run.

Revision ID: b6f1e0a97c23
Revises: a3d92f7c04be
Create Date: 2026-08-28 20:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b6f1e0a97c23"
down_revision: str | None = "a3d92f7c04be"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "seasons", sa.Column("ladder_synced_at", sa.DateTime(), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("seasons", "ladder_synced_at")
