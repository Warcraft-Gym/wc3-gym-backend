"""Flag a signup as out of the pick list

An admin takes a player out of the draft while he goes through the signups:
too few ladder games, a wrong bnet name, a wrong race. The player keeps his
signup and holds no draft slot.

Revision ID: a5c9f2e71b48
Revises: f3a8c71b0d24
Create Date: 2026-09-09 15:40:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a5c9f2e71b48"
down_revision: str | Sequence[str] | None = "f3a8c71b0d24"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "user_season_signup",
        sa.Column(
            "draft_excluded",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )


def downgrade() -> None:
    op.drop_column("user_season_signup", "draft_excluded")
