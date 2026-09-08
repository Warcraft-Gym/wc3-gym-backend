"""Add the season round columns

A GNL round is one or two weeks long, so `number_weeks` and `series_per_week`
named the wrong unit. The round columns take over. The week columns stay,
filled and readable, until the deploy after the one that stops reading them.

Revision ID: a3f9d17c6b40
Revises: d7e3a9c1f5b2
Create Date: 2026-09-09 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a3f9d17c6b40"
down_revision: str | Sequence[str] | None = "d7e3a9c1f5b2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PAIRS = (("number_rounds", "number_weeks"), ("series_per_round", "series_per_week"))


def upgrade() -> None:
    for new, old in PAIRS:
        op.add_column("seasons", sa.Column(new, sa.Integer(), nullable=True))
        op.execute(f"UPDATE seasons SET {new} = {old}")
        # The week column is optional from here on; the code before this deploy
        # still writes it, and the code after this one stops.
        op.alter_column("seasons", old, existing_type=sa.Integer(), nullable=True)


def downgrade() -> None:
    for new, old in PAIRS:
        op.execute(f"UPDATE seasons SET {old} = {new} WHERE {old} IS NULL")
        op.alter_column("seasons", old, existing_type=sa.Integer(), nullable=False)
        op.drop_column("seasons", new)
