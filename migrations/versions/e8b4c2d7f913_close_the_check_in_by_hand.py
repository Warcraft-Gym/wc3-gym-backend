"""Close the check-in by hand

`checkin_closed_at` on `event` and on `cup_leg`: when a runner closed the
check-in of the event or of one round of a cup, cleared by a reopen. Every
row starts null, so every check-in keeps following its window.

Revision ID: e8b4c2d7f913
Revises: d3a8f6c1b294
Create Date: 2026-10-16 18:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e8b4c2d7f913"
down_revision: str | Sequence[str] | None = "d3a8f6c1b294"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# Plain add and drop: a batch rebuild of `event` loses its self-referencing key on SQLite.
def upgrade() -> None:
    for table in ("event", "cup_leg"):
        op.add_column(
            table,
            sa.Column("checkin_closed_at", sa.DateTime(timezone=True), nullable=True),
        )


def downgrade() -> None:
    for table in ("cup_leg", "event"):
        op.drop_column(table, "checkin_closed_at")
