"""One active KOTH signup per battle tag and race

A player is his battle tag, not his Twitch name: an admin signup and a
profile signup both leave the Twitch name blank, and the index that guards
the Twitch name skips blanks. A second generated column holds the folded
battle tag while the signup is active and NULL after it, so one player takes
each race of an event once and a retired signup blocks nothing.

Signups that repeat a key lose their active flag before the index is built.
The lowest id of each key keeps it, so the first signup wins. The downgrade
drops the index and the column; it does not give the flag back.

Revision ID: f1a6c8d3b204
Revises: c5d9e2f47a81
Create Date: 2026-08-31 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f1a6c8d3b204"
down_revision: str | Sequence[str] | None = "c5d9e2f47a81"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

INDEX = "uq_koth_signups_active_battle_tag_race"
ACTIVE_BATTLE_TAG = "CASE WHEN is_active = 1 THEN lower(trim(battle_tag)) END"

# The ids come from a derived table, so the update reads no row it writes
DEACTIVATE_DUPLICATES = """
UPDATE koth_signups SET is_active = 0
WHERE is_active = 1
  AND id NOT IN (
    SELECT id FROM (
      SELECT MIN(id) AS id FROM koth_signups
      WHERE is_active = 1
      GROUP BY event_id, lower(trim(battle_tag)), race
    ) AS first_signups
  )
"""


def upgrade() -> None:
    op.execute(DEACTIVATE_DUPLICATES)
    op.add_column(
        "koth_signups",
        sa.Column(
            "active_battle_tag",
            sqlmodel.sql.sqltypes.AutoString(length=50),
            sa.Computed(ACTIVE_BATTLE_TAG),
            nullable=True,
        ),
    )
    op.create_index(
        INDEX,
        "koth_signups",
        ["event_id", "active_battle_tag", "race"],
        unique=True,
    )


def downgrade() -> None:
    op.drop_index(INDEX, table_name="koth_signups")
    op.drop_column("koth_signups", "active_battle_tag")
