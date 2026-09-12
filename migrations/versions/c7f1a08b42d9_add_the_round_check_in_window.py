"""Add the round check-in window

How many days before a round starts the players of a season may check in for
it; a player cannot answer any earlier.

Revision ID: c7f1a08b42d9
Revises: e2a4c9d17b35
Create Date: 2026-09-13 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c7f1a08b42d9"
down_revision: str | Sequence[str] | None = "e2a4c9d17b35"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "seasons",
        sa.Column("checkin_days", sa.Integer(), nullable=False, server_default="3"),
    )


def downgrade() -> None:
    op.drop_column("seasons", "checkin_days")
