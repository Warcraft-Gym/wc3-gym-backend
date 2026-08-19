"""Drop the stored fantasy score columns

app.services.derived scores every fantasy team and every bet from the map
scores at read time, so these columns are written and never read. The
fantasy_bets.bet_points stake is source data and stays. The downgrade
recreates the dropped columns empty; the derived fill answers the same
numbers.

Revision ID: 9f4b7c1d2ae5
Revises: 3c1064e604d3
Create Date: 2026-08-19 23:55:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9f4b7c1d2ae5"
down_revision: str | Sequence[str] | None = "3c1064e604d3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TEAM_SCORES = (
    "player_points",
    "bench_points",
    "team_points",
    "race_points",
    "bet_points",
    "total_points",
)


def upgrade() -> None:
    for column in TEAM_SCORES:
        op.drop_column("fantasy_teams", column)
    op.drop_column("fantasy_bets", "bet_result")


def downgrade() -> None:
    for column in TEAM_SCORES:
        op.add_column("fantasy_teams", sa.Column(column, sa.Integer(), nullable=True))
    op.add_column("fantasy_bets", sa.Column("bet_result", sa.Integer(), nullable=True))
