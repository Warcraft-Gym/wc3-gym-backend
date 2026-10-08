"""Add a best-of per bracket part and the veto by best-of

A stage names the best-of of each part of its bracket, which the draw writes
onto each round; an event that vetoes by best-of derives each series' veto
from its own best-of and the pool.

Revision ID: c7e2b9d4a613
Revises: a8d3e1f6c924
Create Date: 2026-10-07 20:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c7e2b9d4a613"
down_revision: str | Sequence[str] | None = "a8d3e1f6c924"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "event_stage",
        sa.Column(
            "best_of_by_round",
            sqlmodel.sql.sqltypes.AutoString(length=200),
            nullable=True,
        ),
    )
    op.add_column(
        "event",
        sa.Column(
            "veto_by_best_of", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
    )


def downgrade() -> None:
    op.drop_column("event", "veto_by_best_of")
    op.drop_column("event_stage", "best_of_by_round")
