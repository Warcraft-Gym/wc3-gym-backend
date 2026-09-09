"""Drop the stored round counts

Nothing reads `number_weeks`, `number_rounds` or `series_per_week`. The round
rows are the round count, and `series_per_round` holds the other setting.

Revision ID: c8b5f31a92e0
Revises: a4c1e08b6d27
Create Date: 2026-09-09 02:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c8b5f31a92e0"
down_revision: str | Sequence[str] | None = "a4c1e08b6d27"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

GONE = ("number_weeks", "number_rounds", "series_per_week")


def upgrade() -> None:
    for name in GONE:
        op.drop_column("seasons", name)
    op.alter_column(
        "seasons", "series_per_round", existing_type=sa.Integer(), nullable=False
    )


def downgrade() -> None:
    op.alter_column(
        "seasons", "series_per_round", existing_type=sa.Integer(), nullable=True
    )
    for name in GONE:
        op.add_column("seasons", sa.Column(name, sa.Integer(), nullable=True))
    # The counts come back from the rows and from the column that replaced them
    op.execute(
        "UPDATE seasons SET number_rounds = ("
        " SELECT count(*) FROM season_rounds WHERE season_rounds.season_id = seasons.id"
        ")"
    )
    op.execute("UPDATE seasons SET number_weeks = number_rounds")
    op.execute("UPDATE seasons SET series_per_week = series_per_round")
