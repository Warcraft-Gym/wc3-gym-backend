"""The KOTH crown

Who wears the crown of a division. The crown is a stored fact, so an admin
can empty the throne or pass it on without a game being played. The column
carries no foreign key: an entrant already points at its division, and the
pair of keys would make the two tables a cycle.

Revision ID: d3b7f1c94a28
Revises: c6d2f1a83b95
Create Date: 2026-09-20 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d3b7f1c94a28"
down_revision: str | Sequence[str] | None = "c6d2f1a83b95"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# The crown a night already played: the winner of the last series of its bracket
BACKFILL = """
UPDATE event_division SET king_entrant_id = (
    SELECT CASE WHEN series.player1_score > series.player2_score
                THEN series.entrant1_id ELSE series.entrant2_id END
    FROM series
    WHERE series.division_id = event_division.id
      AND series.player1_score IS NOT NULL
      AND series.player2_score IS NOT NULL
      AND series.player1_score <> series.player2_score
    ORDER BY series.sequence DESC, series.id DESC
    LIMIT 1
)
WHERE EXISTS (
    SELECT 1 FROM event_stage
    WHERE event_stage.event_id = event_division.event_id
      AND event_stage.format = 'koth'
)
"""


def upgrade() -> None:
    op.add_column(
        "event_division", sa.Column("king_entrant_id", sa.Integer(), nullable=True)
    )
    op.execute(sa.text(BACKFILL))


def downgrade() -> None:
    op.drop_column("event_division", "king_entrant_id")
