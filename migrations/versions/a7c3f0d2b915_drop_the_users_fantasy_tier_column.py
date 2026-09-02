"""Drop the users fantasy tier column

The tier lives on the season signup row since d5e8b1c47a90, and nothing
reads the global column any more.

Revision ID: a7c3f0d2b915
Revises: d5e8b1c47a90
Create Date: 2026-09-02 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a7c3f0d2b915"
down_revision: str | Sequence[str] | None = "d5e8b1c47a90"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("users", "fantasy_tier")


def downgrade() -> None:
    op.add_column("users", sa.Column("fantasy_tier", sa.Integer(), nullable=True))
