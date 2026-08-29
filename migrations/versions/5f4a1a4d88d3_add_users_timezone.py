"""Add the player's time zone to users

The profile holds an IANA name, autofilled from the browser, so a series time
can be shown in the player's own zone. The column is nullable and holds no
data, so the downgrade drops it.

Revision ID: 5f4a1a4d88d3
Revises: d1f6b3e94a02
Create Date: 2026-08-29 13:46:01.068818

"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "5f4a1a4d88d3"
down_revision: str | Sequence[str] | None = "e2a7c4d15b93"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column(
            "timezone", sqlmodel.sql.sqltypes.AutoString(length=64), nullable=True
        ),
    )


def downgrade() -> None:
    op.drop_column("users", "timezone")
