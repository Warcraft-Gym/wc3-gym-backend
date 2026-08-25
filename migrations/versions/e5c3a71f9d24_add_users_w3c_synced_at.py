"""Add the time of the last w3champions sync to users

The sync stamps the row on every attempt that reached w3champions, so a
player with no stats reads as "synced, unranked" instead of "never synced",
and a button can skip the players another admin just refreshed. The column
is nullable and holds no data, so the downgrade drops it.

Revision ID: e5c3a71f9d24
Revises: c4e1a9b72d50
Create Date: 2026-08-25 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e5c3a71f9d24"
down_revision: str | Sequence[str] | None = "c4e1a9b72d50"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("w3c_synced_at", sa.DateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "w3c_synced_at")
