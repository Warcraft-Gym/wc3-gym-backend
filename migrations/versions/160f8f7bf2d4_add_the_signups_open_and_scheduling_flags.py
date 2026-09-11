"""Add the signups open and scheduling enabled flags to a season

A season closes its signups when an admin says so, and a one-day cup turns
scheduling off. Both default to on, so every existing season keeps working.

Revision ID: 160f8f7bf2d4
Revises: a5c9f2e71b48
Create Date: 2026-09-11 18:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "160f8f7bf2d4"
down_revision: str | Sequence[str] | None = "a5c9f2e71b48"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for name in ("signups_open", "scheduling_enabled"):
        op.add_column(
            "seasons",
            sa.Column(name, sa.Boolean(), nullable=False, server_default=sa.true()),
        )


def downgrade() -> None:
    op.drop_column("seasons", "scheduling_enabled")
    op.drop_column("seasons", "signups_open")
