"""Drop the season ladder sync stamp

The ladder sync ledger says when every player of the season was read, so the
season answer derives its stamp from those rows and stores none of its own.

Revision ID: d1f6b3e94a02
Revises: c9d4e2a80b71
Create Date: 2026-08-28 21:15:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d1f6b3e94a02"
down_revision: str | None = "c9d4e2a80b71"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("seasons", "ladder_synced_at")


def downgrade() -> None:
    op.add_column(
        "seasons", sa.Column("ladder_synced_at", sa.DateTime(), nullable=True)
    )
