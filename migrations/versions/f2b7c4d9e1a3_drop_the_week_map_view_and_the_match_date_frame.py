"""Drop the week map view and the match date frame

The season_week_map view kept the previous deployment reading while the
rounds migration ran; nothing reads it now. A round's dates replace the
free-text date frame of a match, so the column goes too.

Revision ID: f2b7c4d9e1a3
Revises: a9c4e7d1f2b3
Create Date: 2026-09-07 20:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f2b7c4d9e1a3"
down_revision: str | Sequence[str] | None = "a9c4e7d1f2b3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DROP VIEW season_week_map")
    with op.batch_alter_table("matches") as batch:
        batch.drop_column("date_frame")


def downgrade() -> None:
    with op.batch_alter_table("matches") as batch:
        batch.add_column(sa.Column("date_frame", sa.String(length=50), nullable=True))
    op.execute(
        "CREATE VIEW season_week_map AS SELECT season_id, playday, map_id "
        "FROM season_rounds WHERE map_id IS NOT NULL"
    )
