"""Add cpu_ms to the egress ledger: the process CPU each route's calls spent.

Every existing row starts at 0, so the CPU counts from the first deploy that writes it.

Revision ID: d47305003af9
Revises: e8b4c2d7f913
Create Date: 2026-10-19 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d47305003af9"
down_revision: str | Sequence[str] | None = "e8b4c2d7f913"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "egress_ledger",
        sa.Column("cpu_ms", sa.BigInteger(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("egress_ledger", "cpu_ms")
