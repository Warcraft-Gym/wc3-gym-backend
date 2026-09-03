"""Store a draft position per signup

An admin moves a player in the draft order when the ladder MMR misreads
him. Null means the player sorts by MMR.

Revision ID: e4b7a1c9d2f6
Revises: c8e2a6d4f913
Create Date: 2026-09-03 18:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e4b7a1c9d2f6"
down_revision: str | Sequence[str] | None = "c8e2a6d4f913"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "user_season_signup",
        sa.Column("draft_position", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("user_season_signup", "draft_position")
