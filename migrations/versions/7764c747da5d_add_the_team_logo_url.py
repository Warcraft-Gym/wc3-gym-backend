"""Add the team logo url

Autogenerate also wanted to drop and rebuild six expression indexes, because it renders
`TRIM(BOTH FROM x)` and `trim(x)` differently while the database holds one thing. Those are dropped
from this migration; only the column is real.

Revision ID: 7764c747da5d
Revises: c4d7e9f1a2b3
Create Date: 2026-09-02 19:11:08.023276

"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7764c747da5d"
down_revision: str | Sequence[str] | None = "c4d7e9f1a2b3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "teams",
        sa.Column(
            "icon_url", sqlmodel.sql.sqltypes.AutoString(length=500), nullable=True
        ),
    )


def downgrade() -> None:
    op.drop_column("teams", "icon_url")
