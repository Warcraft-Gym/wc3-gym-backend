"""Drop the stored career total columns

app.services.derived computes the nine career totals from the historical
baseline and the map scores, so these columns are written and never read. The
downgrade recreates them empty; the derived fill answers the same numbers.

Revision ID: 3c1064e604d3
Revises: 300992697182
Create Date: 2026-08-19 23:40:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "3c1064e604d3"
down_revision: str | Sequence[str] | None = "300992697182"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COUNTS = (
    "rating",
    "series_won",
    "series_lost",
    "games_won",
    "games_lost",
    "seasons_played",
)
RATES = ("series_winrate", "games_winrate", "avg_series_per_season")


def upgrade() -> None:
    for column in (*COUNTS, *RATES):
        op.drop_column("player_career_stats", column)


def downgrade() -> None:
    for column in COUNTS:
        op.add_column(
            "player_career_stats", sa.Column(column, sa.Integer(), nullable=True)
        )
    for column in RATES:
        op.add_column(
            "player_career_stats", sa.Column(column, sa.DECIMAL(5, 2), nullable=True)
        )
