"""Remember the bot's series post

The bot's /veto and /announce posts say where the veto stands, so the series
keeps the last post and the veto route edits it after every step.

Revision ID: c4d9e2f7a1b3
Revises: b8e1d4a7c2f9
Create Date: 2026-09-07 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c4d9e2f7a1b3"
down_revision: str | Sequence[str] | None = "b8e1d4a7c2f9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("series", sa.Column("discord_post_command", sa.String(8)))
    op.add_column("series", sa.Column("discord_post_channel_id", sa.String(20)))
    op.add_column("series", sa.Column("discord_post_message_id", sa.String(20)))


def downgrade() -> None:
    op.drop_column("series", "discord_post_message_id")
    op.drop_column("series", "discord_post_channel_id")
    op.drop_column("series", "discord_post_command")
