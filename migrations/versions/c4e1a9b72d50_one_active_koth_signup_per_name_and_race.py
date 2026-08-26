"""One active KOTH signup per twitch name and race

Two chat messages in the same second made two signups, because nothing in
the database stopped the second one. A generated column holds the twitch
name while the signup is active and NULL after it, so the unique index
counts only the active signups and a retired signup blocks nothing.

Signups that repeat a key lose their active flag before the index is
built. The lowest id of each key keeps it, so the first signup wins. The
downgrade drops the index and the column; it does not give the flag back.

Revision ID: c4e1a9b72d50
Revises: 9f4b7c1d2ae5
Create Date: 2026-08-20 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c4e1a9b72d50"
down_revision: str | Sequence[str] | None = "b2e7c4f10d93"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEX = "uq_koth_signups_active_twitch_username_race"
ACTIVE_TWITCH_USERNAME = (
    "CASE WHEN is_active = 1 AND twitch_username <> '' THEN twitch_username END"
)

# The ids come from a derived table, so the update reads no row it writes
DEACTIVATE_DUPLICATES = """
UPDATE koth_signups SET is_active = 0
WHERE is_active = 1
  AND twitch_username IS NOT NULL
  AND twitch_username <> ''
  AND id NOT IN (
    SELECT id FROM (
      SELECT MIN(id) AS id FROM koth_signups
      WHERE is_active = 1
        AND twitch_username IS NOT NULL
        AND twitch_username <> ''
      GROUP BY event_id, twitch_username, race
    ) AS first_signups
  )
"""


def upgrade() -> None:
    op.execute(DEACTIVATE_DUPLICATES)
    op.add_column(
        "koth_signups",
        sa.Column(
            "active_twitch_username",
            sqlmodel.sql.sqltypes.AutoString(length=50),
            sa.Computed(ACTIVE_TWITCH_USERNAME),
            nullable=True,
        ),
    )
    op.create_index(
        INDEX,
        "koth_signups",
        ["event_id", "active_twitch_username", "race"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(INDEX, table_name="koth_signups")
    op.drop_column("koth_signups", "active_twitch_username")
