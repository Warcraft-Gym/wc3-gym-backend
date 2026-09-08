"""Pace the bot post edits

A post row keeps when its subject last changed and when the card was last
edited, so a burst of writes edits each card once per second per channel.

Revision ID: b4c8e1f6a2d9
Revises: e2a9c4d7b1f5
Create Date: 2026-09-08 13:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b4c8e1f6a2d9"
down_revision: str | Sequence[str] | None = "e2a9c4d7b1f5"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("discord_post") as batch:
        batch.add_column(
            sa.Column("changed_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch.add_column(
            sa.Column("edited_at", sa.DateTime(timezone=True), nullable=True)
        )


def downgrade() -> None:
    with op.batch_alter_table("discord_post") as batch:
        batch.drop_column("edited_at")
        batch.drop_column("changed_at")
