"""Store the fantasy tier cuts

The MMR boundaries the admin cut a season's tiers at, so the tier page reopens on
them and a season records what each tier meant. Null until the first Apply.

Revision ID: c4d1e7f9a2b3
Revises: a9c2e4f7b1d6
Create Date: 2026-09-02 22:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c4d1e7f9a2b3"
down_revision: str | Sequence[str] | None = "a9c2e4f7b1d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("seasons", sa.Column("fantasy_tier_cuts", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("seasons", "fantasy_tier_cuts")
