"""Add the cup settings and the cup entrant pins

A cup chooses whether it splits its players into divisions, and holds that
choice in `cup_settings`, beside the event row. Its entrants carry two pins
of their own in `cup_entrant_pin`: placed in the division by hand, and a seed
a reshuffle keeps. Every existing cup gets its settings row, on where it
already holds divisions, and an entrant it placed by hand gets both pins.

Revision ID: c7d2e9a4f183
Revises: a8e3c5f1d276
Create Date: 2026-10-13 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c7d2e9a4f183"
down_revision: str | Sequence[str] | None = "a8e3c5f1d276"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

CUPS = "SELECT id FROM event WHERE kind = 'cup'"


def upgrade() -> None:
    op.create_table(
        "cup_settings",
        sa.Column("event_id", sa.Integer(), nullable=False),
        sa.Column(
            "uses_divisions", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["event.id"],
            name=op.f("fk_cup_settings_event_id_event"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("event_id", name=op.f("pk_cup_settings")),
    )
    op.create_table(
        "cup_entrant_pin",
        sa.Column("entrant_id", sa.Integer(), nullable=False),
        sa.Column(
            "division_pinned", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
        sa.Column(
            "seed_pinned", sa.Boolean(), server_default=sa.false(), nullable=False
        ),
        sa.ForeignKeyConstraint(
            ["entrant_id"],
            ["event_entrant.id"],
            name=op.f("fk_cup_entrant_pin_entrant_id_event_entrant"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("entrant_id", name=op.f("pk_cup_entrant_pin")),
    )
    op.execute(
        "INSERT INTO cup_settings (event_id, uses_divisions) "
        "SELECT e.id, EXISTS (SELECT 1 FROM event_division d WHERE d.event_id = e.id) "
        f"FROM event e WHERE e.id IN ({CUPS})"
    )
    op.execute(
        "INSERT INTO cup_entrant_pin (entrant_id, division_pinned, seed_pinned) "
        "SELECT id, manual_placement, manual_placement FROM event_entrant "
        f"WHERE manual_placement AND event_id IN ({CUPS})"
    )


def downgrade() -> None:
    # A cup's two pins fold back into the one flag the older schema reads
    op.execute(
        "UPDATE event_entrant SET manual_placement = EXISTS ("
        "SELECT 1 FROM cup_entrant_pin p WHERE p.entrant_id = event_entrant.id "
        "AND (p.division_pinned OR p.seed_pinned)) "
        f"WHERE event_id IN ({CUPS})"
    )
    op.drop_table("cup_entrant_pin")
    op.drop_table("cup_settings")
