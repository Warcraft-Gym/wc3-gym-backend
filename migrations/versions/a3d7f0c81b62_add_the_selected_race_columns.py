"""Keep the selected race and the played race of both sides

The league scores a player on the race he selected, where a random pick is
RANDOM, so `race` and `opp_race` now hold that and the two new columns hold
the race actually played. The selected race was never fetched, so no stored
row can be corrected in place; every row is a rebuildable copy of
w3champions data, so the upgrade empties the table and clears
`users.ladder_synced_at`, which makes the next sync refill it.

Revision ID: a3d7f0c81b62
Revises: f8a1c6b3d704
Create Date: 2026-08-28 14:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "a3d7f0c81b62"
down_revision: str | Sequence[str] | None = "f8a1c6b3d704"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RACES = ("RANDOM", "HU", "OC", "NE", "UD")


def race_type() -> sa.Enum:
    """The race enum. Postgres already holds the type, so it is not created again."""
    if op.get_bind().dialect.name == "postgresql":
        return postgresql.ENUM(*RACES, name="race", create_type=False)
    return sa.Enum(*RACES, name="race")


def upgrade() -> None:
    op.add_column(
        "w3c_ladder_matches", sa.Column("played_race", race_type(), nullable=True)
    )
    op.add_column(
        "w3c_ladder_matches", sa.Column("opp_played_race", race_type(), nullable=True)
    )
    op.execute(sa.text("DELETE FROM w3c_ladder_matches"))
    op.execute(sa.text("UPDATE users SET ladder_synced_at = NULL"))


def downgrade() -> None:
    op.drop_column("w3c_ladder_matches", "opp_played_race")
    op.drop_column("w3c_ladder_matches", "played_race")
