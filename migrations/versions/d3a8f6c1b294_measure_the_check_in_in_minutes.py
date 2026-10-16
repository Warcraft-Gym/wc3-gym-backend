"""Measure the check-in in minutes

Two columns on `event`: `checkin_opens_minutes`, how many minutes before the
start the check-in opens, written from `checkin_days`, and
`checkin_closes_minutes`, how many minutes before the start it closes, left
null so every event keeps closing at its draw or its round's end. A cup
played over rounds takes check-ins from sign-up, so early check-in turns on
for every event that holds a `cup_leg` row.

Revision ID: d3a8f6c1b294
Revises: c5f8e1b3d907
Create Date: 2026-10-16 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d3a8f6c1b294"
down_revision: str | Sequence[str] | None = "c5f8e1b3d907"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Plain add and drop: a batch rebuild of `event` loses its self-referencing key on SQLite.
def upgrade() -> None:
    op.add_column(
        "event",
        sa.Column(
            "checkin_opens_minutes",
            sa.Integer(),
            nullable=True,
            server_default="4320",
        ),
    )
    op.add_column(
        "event", sa.Column("checkin_closes_minutes", sa.Integer(), nullable=True)
    )
    op.execute("UPDATE event SET checkin_opens_minutes = checkin_days * 1440")
    op.execute(
        "UPDATE event SET early_checkin = TRUE "
        "WHERE id IN (SELECT event_id FROM cup_leg)"
    )


def downgrade() -> None:
    op.drop_column("event", "checkin_closes_minutes")
    op.drop_column("event", "checkin_opens_minutes")
