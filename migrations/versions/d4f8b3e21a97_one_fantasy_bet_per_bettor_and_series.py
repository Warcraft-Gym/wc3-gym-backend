"""One fantasy bet per bettor and series

Prod holds two identical bets by brittonvol on series 411 (ids 761 and 824),
so the old app counted that bet twice. Nothing but a unique index stops a
second bet: both importers write per row, and a bettor who changes their
pick would otherwise leave two rows that both score. The delete keeps the
highest id of each key, because that row holds the pick the bettor made
last. The delete cannot roll back, so take a dump of the database before
this revision runs.

Revision ID: d4f8b3e21a97
Revises: 13cb8124202b
Create Date: 2026-08-27 12:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d4f8b3e21a97"
down_revision: str | Sequence[str] | None = "13cb8124202b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEX = "uq_fantasy_bets_series_id_user_id"

# The keepers come from a derived table, so the delete reads a result set
# rather than the table it writes.
DEDUPE = """
DELETE FROM fantasy_bets
WHERE id NOT IN (
    SELECT keep_id FROM (
        SELECT MAX(id) AS keep_id
        FROM fantasy_bets
        GROUP BY series_id, user_id
    ) AS keepers
)
"""


def upgrade() -> None:
    op.execute(DEDUPE)
    op.create_index(INDEX, "fantasy_bets", ["series_id", "user_id"], unique=True)


def downgrade() -> None:
    op.drop_index(INDEX, table_name="fantasy_bets")
