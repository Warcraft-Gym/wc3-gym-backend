"""Add the announcement subscribers

A member who takes the cup announcement role on Home is one
`announcement_subscriber` row, keyed by the Discord account the role is
granted to. No row exists before the first switch.

Revision ID: c5f8e1b3d907
Revises: a4d7e2c9f150
Create Date: 2026-10-15 19:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c5f8e1b3d907"
down_revision: str | Sequence[str] | None = "a4d7e2c9f150"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "announcement_subscriber",
        sa.Column("discord_id", sa.String(length=50), nullable=False),
        sa.Column(
            "subscribed_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("discord_id", name=op.f("pk_announcement_subscriber")),
    )


def downgrade() -> None:
    op.drop_table("announcement_subscriber")
