"""Add the egress snapshots

A daily job copies each statement's cumulative calls and rows from
pg_stat_statements into egress_snapshot, with the statement text stored once
in egress_statement. New tables only, so the running code is unaffected.

Revision ID: a7d2e5c81f94
Revises: c3e9a7d1f205
Create Date: 2026-09-26 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a7d2e5c81f94"
down_revision: str | Sequence[str] | None = "c3e9a7d1f205"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "egress_statement",
        sa.Column("queryid", sa.BigInteger(), nullable=False),
        sa.Column("dbid", sa.BigInteger(), nullable=False),
        sa.Column("query", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("queryid", "dbid", name=op.f("pk_egress_statement")),
    )
    op.create_table(
        "egress_snapshot",
        sa.Column("taken_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("queryid", sa.BigInteger(), nullable=False),
        sa.Column("dbid", sa.BigInteger(), nullable=False),
        sa.Column("calls", sa.BigInteger(), nullable=False),
        sa.Column("rows", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint(
            "taken_at", "queryid", "dbid", name=op.f("pk_egress_snapshot")
        ),
    )


def downgrade() -> None:
    op.drop_table("egress_snapshot")
    op.drop_table("egress_statement")
