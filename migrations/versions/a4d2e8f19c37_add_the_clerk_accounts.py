"""Add the Clerk accounts

Every authenticated request asked Clerk's API which Discord account the session
belongs to. The answer never changes, so a row keeps it from the first request on.

Revision ID: a4d2e8f19c37
Revises: c3e9b7f24a10
Create Date: 2026-08-30 19:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a4d2e8f19c37"
down_revision: str | Sequence[str] | None = "c3e9b7f24a10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "clerk_account",
        sa.Column(
            "clerk_user_id", sqlmodel.sql.sqltypes.AutoString(length=64), nullable=False
        ),
        sa.Column(
            "discord_id", sqlmodel.sql.sqltypes.AutoString(length=50), nullable=False
        ),
        sa.PrimaryKeyConstraint("clerk_user_id", name=op.f("pk_clerk_account")),
    )


def downgrade() -> None:
    op.drop_table("clerk_account")
