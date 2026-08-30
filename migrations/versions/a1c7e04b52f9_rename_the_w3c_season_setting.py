"""Rename the current_wc3_season setting to current_w3c_season

The vendor is w3champions, so every reference spells it w3c. The pinned row
is edited by hand a few times a year; only its key changes.

Revision ID: a1c7e04b52f9
Revises: 5f4a1a4d88d3
Create Date: 2026-08-30 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "a1c7e04b52f9"
down_revision: str | Sequence[str] | None = "c7a5e3f10b28"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

settings = sa.table("settings", sa.column("key", sa.String))


def rename(before: str, after: str) -> None:
    op.execute(settings.update().where(settings.c.key == before).values(key=after))


def upgrade() -> None:
    rename("current_wc3_season", "current_w3c_season")


def downgrade() -> None:
    rename("current_w3c_season", "current_wc3_season")
