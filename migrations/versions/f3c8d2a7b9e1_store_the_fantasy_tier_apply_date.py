"""Store the fantasy tier apply date

A player's tier derives from his MMR on the date the tiers were applied, so
the season records it. Null until the first Apply after this revision.

Revision ID: f3c8d2a7b9e1
Revises: e2b7a9c4d1f6
Create Date: 2026-09-03 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f3c8d2a7b9e1"
down_revision: str | Sequence[str] | None = "e2b7a9c4d1f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "seasons",
        sa.Column(
            "fantasy_tiers_applied_at", sa.DateTime(timezone=True), nullable=True
        ),
    )


def downgrade() -> None:
    op.drop_column("seasons", "fantasy_tiers_applied_at")
