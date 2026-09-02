"""Drop the team logo column

Every logo is served from Vercel Blob through `teams.icon_url`; the bytes column had no reader left.

Revision ID: a9c2e4f7b1d6
Revises: d5e8b1c47a90
Create Date: 2026-09-02 21:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a9c2e4f7b1d6"
down_revision: str | Sequence[str] | None = "d5e8b1c47a90"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_column("teams", "icon")


def downgrade() -> None:
    op.add_column("teams", sa.Column("icon", sa.LargeBinary(), nullable=True))
