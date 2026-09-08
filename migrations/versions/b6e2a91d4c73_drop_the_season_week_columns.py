"""Drop the season week columns

Nothing reads `number_weeks` or `series_per_week` any more: the API, the admin
frontend and the standings shortcode all read the round columns. The round
columns become required, which is what the week columns were.

Revision ID: b6e2a91d4c73
Revises: a3f9d17c6b40
Create Date: 2026-09-09 18:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b6e2a91d4c73"
down_revision: str | Sequence[str] | None = "a3f9d17c6b40"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

PAIRS = (("number_rounds", "number_weeks"), ("series_per_round", "series_per_week"))


def upgrade() -> None:
    for new, old in PAIRS:
        op.drop_column("seasons", old)
        op.alter_column("seasons", new, existing_type=sa.Integer(), nullable=False)


def downgrade() -> None:
    for new, old in PAIRS:
        op.add_column("seasons", sa.Column(old, sa.Integer(), nullable=True))
        op.execute(f"UPDATE seasons SET {old} = {new}")
        op.alter_column("seasons", old, existing_type=sa.Integer(), nullable=False)
        op.alter_column("seasons", new, existing_type=sa.Integer(), nullable=True)
