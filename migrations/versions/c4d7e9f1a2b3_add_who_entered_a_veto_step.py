"""Add who entered a veto step

A veto that happened in a chat is typed in afterwards by one player, so a
step records the user who entered it. A live step names the player who took
it; a step entered for the other side names the one who typed it.

Revision ID: c4d7e9f1a2b3
Revises: e2c9b47a1d63
Create Date: 2026-09-01 22:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c4d7e9f1a2b3"
down_revision: str | Sequence[str] | None = "e2c9b47a1d63"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

VETO_STEP = "series_veto_step"
FK = "fk_series_veto_step_entered_by_users"


def upgrade() -> None:
    with op.batch_alter_table(VETO_STEP) as batch:
        batch.add_column(sa.Column("entered_by", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            op.f(FK), "users", ["entered_by"], ["id"], ondelete="SET NULL"
        )


def downgrade() -> None:
    with op.batch_alter_table(VETO_STEP) as batch:
        batch.drop_constraint(op.f(FK), type_="foreignkey")
        batch.drop_column("entered_by")
