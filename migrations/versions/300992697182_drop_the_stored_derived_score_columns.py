"""Drop the stored derived score columns

app.services.derived computes the series points, the match scores and the team
standings from the map scores, so these seven columns are written and never read.
The downgrade recreates them empty; the derived fill answers the same numbers.

Revision ID: 300992697182
Revises: a66160626904
Create Date: 2026-08-19 15:37:44.969456

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "300992697182"
down_revision: str | Sequence[str] | None = "a66160626904"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DROPPED = {
    "series": ("player1_points", "player2_points"),
    "matches": ("team1_score", "team2_score"),
    "team_season": ("final_score", "points_available", "points_against"),
}


def upgrade() -> None:
    for table, columns in DROPPED.items():
        for column in columns:
            op.drop_column(table, column)


def downgrade() -> None:
    for table, columns in DROPPED.items():
        for column in columns:
            op.add_column(table, sa.Column(column, sa.Integer(), nullable=True))
