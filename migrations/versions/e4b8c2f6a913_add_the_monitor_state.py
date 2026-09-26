"""Add the monitor state

One row per monitor check with its last level, so the egress snapshot
posts an alert once per change of level. A new table only, so the running
code is unaffected.

Revision ID: e4b8c2f6a913
Revises: a7d2e5c81f94
Create Date: 2026-09-26 14:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e4b8c2f6a913"
down_revision: str | Sequence[str] | None = "a7d2e5c81f94"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "monitor_state",
        sa.Column("key", sa.Text(), nullable=False),
        sa.Column("level", sa.Text(), nullable=False),
        sa.Column("since", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("key", name=op.f("pk_monitor_state")),
    )


def downgrade() -> None:
    op.drop_table("monitor_state")
