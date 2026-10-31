"""Add the cup entrant line

A cup orders its sign-ups in a line: the first places are in, and the rest
wait on its waitlist. `cup_entrant_line` holds when each entrant last signed
up, and whether a runner let it in by hand, so the line never sends it back.
An entrant with no row stands at its row's creation, so nothing is filled.

Revision ID: f4a9c2e7d138
Revises: e2b7c4f9a816
Create Date: 2026-10-27 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f4a9c2e7d138"
down_revision: str | Sequence[str] | None = "e2b7c4f9a816"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "cup_entrant_line",
        sa.Column("entrant_id", sa.Integer(), nullable=False),
        sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("held_in", sa.Boolean(), server_default=sa.false(), nullable=False),
        sa.ForeignKeyConstraint(
            ["entrant_id"],
            ["event_entrant.id"],
            name=op.f("fk_cup_entrant_line_entrant_id_event_entrant"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("entrant_id", name=op.f("pk_cup_entrant_line")),
    )


def downgrade() -> None:
    op.drop_table("cup_entrant_line")
