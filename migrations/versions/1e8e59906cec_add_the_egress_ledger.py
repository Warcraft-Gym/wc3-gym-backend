"""Add the egress ledger

One row per day, route and method with what the calls of that route cost
the database. The middleware adds to it after every request. A new table
only, so the running code is unaffected.

Revision ID: 1e8e59906cec
Revises: d3b7f1c94a28
Create Date: 2026-09-23 12:23:20.698540

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "1e8e59906cec"
down_revision: str | Sequence[str] | None = "d3b7f1c94a28"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "egress_ledger",
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("route", sa.Text(), nullable=False),
        sa.Column("method", sa.Text(), nullable=False),
        sa.Column("calls", sa.BigInteger(), nullable=False),
        sa.Column("statements", sa.BigInteger(), nullable=False),
        sa.Column("rows", sa.BigInteger(), nullable=False),
        sa.Column("bytes", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint(
            "day", "route", "method", name=op.f("pk_egress_ledger")
        ),
    )


def downgrade() -> None:
    op.drop_table("egress_ledger")
