"""Keep the bot's posts in their own table

A discord_post row names a post the bot made and the row it is about, so a
write edits every post of its subject and the series table carries no bot
state. The three series columns move into the table.

Revision ID: d5e0f3a8b2c4
Revises: c4d9e2f7a1b3
Create Date: 2026-09-07 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d5e0f3a8b2c4"
down_revision: str | Sequence[str] | None = "c4d9e2f7a1b3"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "discord_post",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("kind", sqlmodel.sql.sqltypes.AutoString(length=16), nullable=False),
        sa.Column("subject_id", sa.Integer(), nullable=False),
        sa.Column(
            "channel_id", sqlmodel.sql.sqltypes.AutoString(length=20), nullable=False
        ),
        sa.Column(
            "message_id", sqlmodel.sql.sqltypes.AutoString(length=20), nullable=False
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_discord_post")),
        sa.UniqueConstraint("message_id", name=op.f("uq_discord_post_message_id")),
    )
    op.create_index(
        "ix_discord_post_kind_subject_id", "discord_post", ["kind", "subject_id"]
    )
    op.execute(
        "INSERT INTO discord_post (kind, subject_id, channel_id, message_id) "
        "SELECT discord_post_command, id, discord_post_channel_id, discord_post_message_id "
        "FROM series WHERE discord_post_message_id IS NOT NULL"
    )
    op.drop_column("series", "discord_post_message_id")
    op.drop_column("series", "discord_post_channel_id")
    op.drop_column("series", "discord_post_command")


def downgrade() -> None:
    op.add_column("series", sa.Column("discord_post_command", sa.String(8)))
    op.add_column("series", sa.Column("discord_post_channel_id", sa.String(20)))
    op.add_column("series", sa.Column("discord_post_message_id", sa.String(20)))
    # The newest post of each series goes back on the row; the others are lost
    newest = (
        "(SELECT p.{column} FROM discord_post p WHERE p.subject_id = series.id "
        "AND p.kind IN ('veto', 'announce') ORDER BY p.id DESC LIMIT 1)"
    )
    op.execute(
        "UPDATE series SET "
        f"discord_post_command = {newest.format(column='kind')}, "
        f"discord_post_channel_id = {newest.format(column='channel_id')}, "
        f"discord_post_message_id = {newest.format(column='message_id')}"
    )
    op.drop_index("ix_discord_post_kind_subject_id", "discord_post")
    op.drop_table("discord_post")
