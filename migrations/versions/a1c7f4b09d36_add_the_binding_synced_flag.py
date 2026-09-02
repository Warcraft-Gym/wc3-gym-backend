"""Add the binding synced flag

An admin now chooses per binding whether the app grants and revokes its role.
Every binding but a hand-managed admin one is marked synced, so the guild sees
exactly what it saw before.

Revision ID: a1c7f4b09d36
Revises: f3c8d2a7b9e1
Create Date: 2026-09-03 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1c7f4b09d36"
down_revision: str | Sequence[str] | None = "f3c8d2a7b9e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("discord_role_binding") as batch:
        batch.add_column(
            sa.Column("synced", sa.Boolean(), nullable=False, server_default=sa.false())
        )
    op.execute("UPDATE discord_role_binding SET synced = true WHERE kind != 'admin'")


def downgrade() -> None:
    with op.batch_alter_table("discord_role_binding") as batch:
        batch.drop_column("synced")
