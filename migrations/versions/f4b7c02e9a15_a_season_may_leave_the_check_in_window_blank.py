"""A season may leave the check-in window blank

A blank window keeps the check-in open all season.

Revision ID: f4b7c02e9a15
Revises: c7f1a08b42d9
Create Date: 2026-09-13 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f4b7c02e9a15"
down_revision: str | Sequence[str] | None = "c7f1a08b42d9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

# The expression key of seasons, as f7a2c95e3b18 built it
KEY = "CREATE UNIQUE INDEX uq_seasons_name ON seasons (lower(trim(name)))"


def _nullable(nullable: bool) -> None:
    # batch mode: SQLite rewrites the table, which is how it drops a NOT NULL at all
    with op.batch_alter_table("seasons") as batch:
        batch.alter_column(
            "checkin_days",
            existing_type=sa.Integer(),
            existing_server_default="3",
            nullable=nullable,
        )
    if op.get_bind().dialect.name == "sqlite":
        # the rewrite copies only the indexes SQLAlchemy can reflect, and an
        # expression index is not one of them, so the key goes back by hand
        op.execute(KEY)


def upgrade() -> None:
    _nullable(True)


def downgrade() -> None:
    op.execute("UPDATE seasons SET checkin_days = 3 WHERE checkin_days IS NULL")
    _nullable(False)
