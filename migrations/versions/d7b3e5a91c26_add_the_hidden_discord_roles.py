"""Add the hidden Discord roles

An admin hides a guild role the app must never touch, and the row keeps it
hidden for every admin. A hidden role cannot be bound.

Revision ID: d7b3e5a91c26
Revises: b6d2f04a83c1
Create Date: 2026-09-03 15:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d7b3e5a91c26"
down_revision: str | Sequence[str] | None = "b6d2f04a83c1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "discord_role_hidden",
        sa.Column(
            "discord_role", sqlmodel.sql.sqltypes.AutoString(length=50), nullable=False
        ),
        sa.PrimaryKeyConstraint("discord_role", name=op.f("pk_discord_role_hidden")),
    )


def downgrade() -> None:
    op.drop_table("discord_role_hidden")
