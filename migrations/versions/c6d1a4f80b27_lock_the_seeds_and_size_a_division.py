"""Lock the seeds and size a division

Two additive columns. `event_stage.seeds_locked_at` stamps the moment an
admin froze the seeds of a stage, and a later seed write is refused.
`event_division.size` holds how many entrants a division takes when the cut
counts from the top instead of reading a lower bound. Both are nullable and
hold no data, so the downgrade drops them.

Revision ID: c6d1a4f80b27
Revises: b2e7f19c40a3
Create Date: 2026-09-13 23:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c6d1a4f80b27"
down_revision: str | Sequence[str] | None = "b2e7f19c40a3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "event_stage",
        sa.Column("seeds_locked_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column("event_division", sa.Column("size", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("event_division", "size")
    op.drop_column("event_stage", "seeds_locked_at")
