"""Add the series replays

A series keeps one replay slot per game. The file goes to Vercel Blob, the way
a team logo does, and the row holds its URL and who uploaded it when.

Revision ID: a3f7c2d9e5b1
Revises: e4b7a1c9d2f6
Create Date: 2026-09-04 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a3f7c2d9e5b1"
down_revision: str | Sequence[str] | None = "e4b7a1c9d2f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

REPLAY = "series_replay"


def upgrade() -> None:
    op.create_table(
        REPLAY,
        sa.Column("series_id", sa.Integer(), nullable=False),
        sa.Column("game_no", sa.Integer(), nullable=False),
        sa.Column("url", sa.String(length=500), nullable=False),
        sa.Column("uploaded_by", sa.Integer(), nullable=True),
        sa.Column("uploaded_at", sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(
            ["series_id"],
            ["series.id"],
            name=op.f("fk_series_replay_series_id_series"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["uploaded_by"],
            ["users.id"],
            name=op.f("fk_series_replay_uploaded_by_users"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("series_id", "game_no", name=op.f("pk_series_replay")),
    )


def downgrade() -> None:
    op.drop_table(REPLAY)
