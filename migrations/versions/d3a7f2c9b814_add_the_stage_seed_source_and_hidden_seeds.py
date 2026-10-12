"""Add the stage seed source and the hidden seeds switch

A stage names how the draw seeds an entrant that has no seed yet; an event
may hide its seed numbers from every reader who does not run it.

Revision ID: d3a7f2c9b814
Revises: c7e2b9d4a613
Create Date: 2026-10-12 03:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d3a7f2c9b814"
down_revision: str | Sequence[str] | None = "c7e2b9d4a613"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "event_stage",
        sa.Column(
            "seed_source",
            sqlmodel.sql.sqltypes.AutoString(length=20),
            server_default="mmr",
            nullable=False,
        ),
    )
    op.add_column(
        "event",
        sa.Column(
            "hide_seeds", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
    )


def downgrade() -> None:
    op.drop_column("event", "hide_seeds")
    op.drop_column("event_stage", "seed_source")
