"""An admin can ban a player

The ban is one nullable stamp on the player row. It never refuses a signup:
the entrant read carries a `banned` warning and an admin decides. The column
is nullable and holds no data, so the downgrade drops it.

Revision ID: b2e7f19c40a3
Revises: 3d5e9a1c7b62
Create Date: 2026-09-13 22:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b2e7f19c40a3"
down_revision: str | Sequence[str] | None = "3d5e9a1c7b62"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users", sa.Column("banned_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("users", "banned_at")
