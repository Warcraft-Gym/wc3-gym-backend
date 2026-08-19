"""Add the season score system

Every season took its score system from the settings row, so the backfill copies that
row onto every season. Without the row the seasons keep the "standard" default.

Revision ID: a66160626904
Revises: 658616cf0c2b
Create Date: 2026-08-19 14:59:16.366000

"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a66160626904"
down_revision: str | Sequence[str] | None = "658616cf0c2b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

seasons = sa.table("seasons", sa.column("score_system", sa.String))
settings = sa.table(
    "settings", sa.column("key", sa.String), sa.column("value", sa.String)
)


def upgrade() -> None:
    op.add_column(
        "seasons",
        sa.Column(
            "score_system",
            sqlmodel.sql.sqltypes.AutoString(length=20),
            nullable=False,
            server_default="standard",
        ),
    )

    configured = (
        sa.select(settings.c.value)
        .where(
            settings.c.key == "score_system",
            settings.c.value.is_not(None),
            settings.c.value != "",
        )
        .limit(1)
        .scalar_subquery()
    )
    op.execute(
        seasons.update().values(score_system=configured).where(configured.is_not(None))
    )


def downgrade() -> None:
    op.drop_column("seasons", "score_system")
