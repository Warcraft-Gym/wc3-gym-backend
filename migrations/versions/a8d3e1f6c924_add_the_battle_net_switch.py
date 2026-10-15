"""Add the switch that makes an event ask for a Battle.net link

The eligibility check reads a battle tag W3Champions rates; an event that also
turns this on asks for the tag to be verified through Battle.net.

Revision ID: a8d3e1f6c924
Revises: f4c2a7e9b351
Create Date: 2026-10-06 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a8d3e1f6c924"
down_revision: str | Sequence[str] | None = "f4c2a7e9b351"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "event",
        sa.Column(
            "bnet_required", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
    )


def downgrade() -> None:
    op.drop_column("event", "bnet_required")
