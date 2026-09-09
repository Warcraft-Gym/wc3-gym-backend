"""Add the series games

A series keeps one row per game: the side that won it and the map it was
played on. The two scores stay the total, and these rows say how the total
was reached, which a 2-1 cannot.

Revision ID: f3a8c71b0d24
Revises: d4b6e2f1c907
Create Date: 2026-09-09 13:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f3a8c71b0d24"
down_revision: str | Sequence[str] | None = "d4b6e2f1c907"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

GAME = "series_game"


def upgrade() -> None:
    op.create_table(
        GAME,
        sa.Column("series_id", sa.Integer(), nullable=False),
        sa.Column("game_no", sa.Integer(), nullable=False),
        sa.Column("winner_side", sa.String(length=1), nullable=False),
        sa.Column("map_id", sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(
            ["series_id"],
            ["series.id"],
            name=op.f("fk_series_game_series_id_series"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["map_id"],
            ["maps.id"],
            name=op.f("fk_series_game_map_id_maps"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("series_id", "game_no", name=op.f("pk_series_game")),
    )


def downgrade() -> None:
    op.drop_table(GAME)
