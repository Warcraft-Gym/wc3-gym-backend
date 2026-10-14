"""Add the custom game cup

A cup can be a custom game, played on one map of its pool with no veto, every
game of a series on it. `cup_settings.custom_game` holds the choice; every
existing cup is no custom game.

Revision ID: a4d7e2c9f150
Revises: f2a6c3d8b417
Create Date: 2026-10-15 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a4d7e2c9f150"
down_revision: str | Sequence[str] | None = "f2a6c3d8b417"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("cup_settings") as batch:
        batch.add_column(
            sa.Column(
                "custom_game", sa.Boolean(), server_default=sa.false(), nullable=False
            )
        )


def downgrade() -> None:
    with op.batch_alter_table("cup_settings") as batch:
        batch.drop_column("custom_game")
