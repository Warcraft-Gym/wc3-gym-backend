"""Add the profile links and the Discord avatar

A player's profile carries the channels they stream on and the avatar image
of their Discord account. The links are entered by the player; the avatar is
written by the app when the login reads the Discord account.

Revision ID: e2a4c9d17b35
Revises: 75b9f3b280c2
Create Date: 2026-09-12 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e2a4c9d17b35"
down_revision: str | Sequence[str] | None = "75b9f3b280c2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users", sa.Column("twitch_url", sa.String(length=200), nullable=True)
    )
    op.add_column(
        "users", sa.Column("youtube_url", sa.String(length=200), nullable=True)
    )
    op.add_column(
        "users", sa.Column("avatar_url", sa.String(length=300), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("users", "avatar_url")
    op.drop_column("users", "youtube_url")
    op.drop_column("users", "twitch_url")
