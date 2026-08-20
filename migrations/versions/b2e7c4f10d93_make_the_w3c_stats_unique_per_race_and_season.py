"""Make the w3c stats unique per user, race and season

The sync reads the rows of a player and then writes them, so two syncs of
one player could both find no row and both insert one. The unique index
stops the duplicate. The delete first removes the duplicates the database
already holds, and keeps the highest id of each key because that row is
the one the last sync wrote. The delete cannot roll back, so take a dump
of the database before this revision runs.

Revision ID: b2e7c4f10d93
Revises: 9f4b7c1d2ae5
Create Date: 2026-08-20 10:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b2e7c4f10d93"
down_revision: str | Sequence[str] | None = "b7e2d4a91c05"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEX = "uq_w3cstats_user_id_race_wc3_season"

# MySQL 5.7 cannot read the table it deletes from, so the keepers go
# through a derived table, which MySQL materialises first.
DEDUPE = """
DELETE FROM w3cstats
WHERE id NOT IN (
    SELECT keep_id FROM (
        SELECT MAX(id) AS keep_id
        FROM w3cstats
        GROUP BY user_id, race, wc3_season
    ) AS keepers
)
"""


def upgrade() -> None:
    op.execute(DEDUPE)
    op.create_index(INDEX, "w3cstats", ["user_id", "race", "wc3_season"], unique=True)


def downgrade() -> None:
    op.drop_index(INDEX, table_name="w3cstats")
