"""Rename the week map rule to fixed

A season's map_rules names one rule per game. The rule that claims game 1 for
the round's map was called "week", which said when the map was chosen, not what
it is. It is now "fixed".

Revision ID: a4c1e08b6d27
Revises: d7e3a9c1f5b2
Create Date: 2026-09-09 10:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a4c1e08b6d27"
down_revision: str | None = "d7e3a9c1f5b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # No other rule name holds "week", so a plain replace is enough
    op.execute("UPDATE seasons SET map_rules = replace(map_rules, 'week', 'fixed')")


def downgrade() -> None:
    op.execute("UPDATE seasons SET map_rules = replace(map_rules, 'fixed', 'week')")
