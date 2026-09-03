"""Record where a ladder season was read from

A ledger row stamped when a w3champions season was read, not from where. A
season first read for a late window was never read again for an earlier one.
Null on the rows older than this revision, which reads them once more.

Revision ID: c8e2a6d4f913
Revises: d7b3e5a91c26
Create Date: 2026-09-03 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c8e2a6d4f913"
down_revision: str | Sequence[str] | None = "d7b3e5a91c26"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "ladder_sync",
        sa.Column("read_from", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("ladder_sync", "read_from")
