"""Add db_bytes to the egress ledger: the bytes each route's database connections received.

Revision ID: c9e2a4d61b07
Revises: b4c8e1f37a20
Create Date: 2026-09-28 13:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c9e2a4d61b07"
down_revision: str | Sequence[str] | None = "b4c8e1f37a20"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "egress_ledger",
        sa.Column("db_bytes", sa.BigInteger(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("egress_ledger", "db_bytes")
