"""Add an event's lowest MMR and the switch that makes its bounds refuse

An event names the lowest MMR it takes beside the highest, and an event with
the switch on refuses a signup outside its bounds, or of a player whose battle
tag is not Battle.net-verified and rated, instead of only warning.

Revision ID: f4c2a7e9b351
Revises: e3b9c6d2f418
Create Date: 2026-10-06 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f4c2a7e9b351"
down_revision: str | Sequence[str] | None = "e3b9c6d2f418"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("event", sa.Column("mmr_min", sa.Integer(), nullable=True))
    op.add_column(
        "event",
        sa.Column(
            "eligibility_required",
            sa.Boolean(),
            server_default=sa.false(),
            nullable=False,
        ),
    )


def downgrade() -> None:
    op.drop_column("event", "eligibility_required")
    op.drop_column("event", "mmr_min")
