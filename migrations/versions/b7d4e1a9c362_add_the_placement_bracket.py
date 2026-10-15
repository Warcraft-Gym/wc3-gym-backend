"""Add the placement bracket

A stage may play a placement bracket: every round splits each group into its
winners and its losers, so the last round decides every place. The stage names
how many losses end a player's run; null plays every place.

Revision ID: b7d4e1a9c362
Revises: f3c8a1d6e027
Create Date: 2026-10-11 20:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b7d4e1a9c362"
down_revision: str | Sequence[str] | None = "f3c8a1d6e027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "sqlite":
        # A label is usable only by the transactions that follow the one adding it
        with op.get_context().autocommit_block():
            op.execute("ALTER TYPE stageformat ADD VALUE IF NOT EXISTS 'placement'")
    op.add_column(
        "event_stage", sa.Column("placement_lives", sa.Integer(), nullable=True)
    )


def downgrade() -> None:
    # Postgres keeps an enum label once added, so a placement stage falls back
    # to the single elimination a run of one loss already is
    op.execute(
        "UPDATE event_stage SET format = 'single_elimination' "
        "WHERE format = 'placement'"
    )
    op.drop_column("event_stage", "placement_lives")
