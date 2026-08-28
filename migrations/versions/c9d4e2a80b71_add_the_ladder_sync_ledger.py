"""Add the ladder sync ledger

w3champions serves matches per player and per w3champions season, and a GNL
season spans a set of those seasons. One row per pair says which of them have
been read, so a resync skips the closed ones it already finished and the open
one is re-read from its own stamp.

Revision ID: c9d4e2a80b71
Revises: b6f1e0a97c23
Create Date: 2026-08-28 21:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c9d4e2a80b71"
down_revision: str | None = "b6f1e0a97c23"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ladder_sync",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("wc3_season", sa.Integer(), nullable=False),
        sa.Column("synced_at", sa.DateTime(), nullable=False),
        sa.Column("complete", sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_ladder_sync_user_id_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_ladder_sync")),
    )
    op.create_index(
        "uq_ladder_sync_user_season",
        "ladder_sync",
        ["user_id", "wc3_season"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index("uq_ladder_sync_user_season", "ladder_sync")
    op.drop_table("ladder_sync")
