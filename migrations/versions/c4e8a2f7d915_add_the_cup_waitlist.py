"""Add the cup waitlist

A cup that is drawn or full puts a new signup on its waitlist instead of
refusing it; the entrant row carries when it went there, and a runner lets it
in or swaps it for a player who has not played.

Revision ID: c4e8a2f7d915
Revises: d3a7f2c9b814
Create Date: 2026-10-12 16:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c4e8a2f7d915"
down_revision: str | Sequence[str] | None = "d3a7f2c9b814"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "event_entrant",
        sa.Column("waitlisted_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("event_entrant", "waitlisted_at")
