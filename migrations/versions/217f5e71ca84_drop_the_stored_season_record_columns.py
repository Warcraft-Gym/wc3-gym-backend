"""Drop the stored season record columns

app.services.derived counts the games, the wins, the losses and the matchup
history of a player from the series he stood in, so these four columns are
written and never read. The downgrade recreates them empty; the derived fill
answers the same numbers.

Revision ID: 217f5e71ca84
Revises: e5c3a71f9d24
Create Date: 2026-08-26 10:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "217f5e71ca84"
down_revision: str | Sequence[str] | None = "e5c3a71f9d24"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "user_team_season"
COUNTS = ("games", "wins", "losses")


def upgrade() -> None:
    for column in (*COUNTS, "matchup_history"):
        op.drop_column(TABLE, column)


def downgrade() -> None:
    for column in COUNTS:
        op.add_column(TABLE, sa.Column(column, sa.Integer(), nullable=True))
    op.add_column(TABLE, sa.Column("matchup_history", sa.JSON(), nullable=True))
