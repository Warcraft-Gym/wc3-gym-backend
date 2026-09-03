"""Store a draft MMR per signup

An admin sets it during the season draft when the ladder MMR misreads a
player. Null means the ladder MMR stands.

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
        sa.Column("mmr_override", sa.Integer(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("user_season_signup", "mmr_override")
