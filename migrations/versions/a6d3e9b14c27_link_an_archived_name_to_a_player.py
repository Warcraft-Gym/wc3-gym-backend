"""Link an archived name to a player

An archived night names its players as the source wrote them. A reviewed
link points such a name at the player's account, so the name can show that
player's profile.

Revision ID: a6d3e9b14c27
Revises: d2a8f5c1e736
Create Date: 2026-10-08 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a6d3e9b14c27"
down_revision: str | Sequence[str] | None = "d2a8f5c1e736"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("historical_participant") as batch:
        batch.add_column(sa.Column("user_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            op.f("fk_historical_participant_user_id_users"),
            "users",
            ["user_id"],
            ["id"],
            ondelete="SET NULL",
        )
        batch.create_index(
            op.f("ix_historical_participant_user_id"), ["user_id"], unique=False
        )


def downgrade() -> None:
    with op.batch_alter_table("historical_participant") as batch:
        batch.drop_index(op.f("ix_historical_participant_user_id"))
        batch.drop_constraint(
            op.f("fk_historical_participant_user_id_users"), type_="foreignkey"
        )
        batch.drop_column("user_id")
