"""Add the announcement subscriber status: subscribed, or declined and not asked again.

Every existing row records a member who took the role, so the server default
keeps each of them subscribed, and the code before this one reads the table
unchanged during the deploy.

Revision ID: e2b7c4f9a816
Revises: c8f3a6d1e925
Create Date: 2026-10-25 16:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e2b7c4f9a816"
down_revision: str | Sequence[str] | None = "c8f3a6d1e925"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "announcement_subscriber",
        sa.Column(
            "status",
            sa.String(length=10),
            nullable=False,
            server_default="subscribed",
        ),
    )


def downgrade() -> None:
    op.drop_column("announcement_subscriber", "status")
