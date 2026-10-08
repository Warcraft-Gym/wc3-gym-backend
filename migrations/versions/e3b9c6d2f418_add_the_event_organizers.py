"""Add the event organizers, an event's minimum and its cancel stamp

An organizer is a Discord account an admin granted, or one whose request an
admin approved; it creates events and runs the ones it holds a row of. An
event names the fewest entrants it is played with, and a cancelled event
carries the time it was called off.

Revision ID: e3b9c6d2f418
Revises: d2a8f5c1e736
Create Date: 2026-10-05 18:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e3b9c6d2f418"
down_revision: str | Sequence[str] | None = "d2a8f5c1e736"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "organizer_grant",
        sa.Column("discord_id", sa.String(length=50), nullable=False),
        sa.Column("name", sa.String(length=50), nullable=False),
        sa.Column("granted_by", sa.String(length=50), nullable=False),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("discord_id", name=op.f("pk_organizer_grant")),
    )
    op.create_table(
        "organizer_request",
        sa.Column("discord_id", sa.String(length=50), nullable=False),
        sa.Column("name", sa.String(length=50), nullable=False),
        sa.Column("note", sa.String(length=300), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("discord_id", name=op.f("pk_organizer_request")),
    )
    op.create_table(
        "event_organizer",
        sa.Column("event_id", sa.Integer(), nullable=False),
        sa.Column("discord_id", sa.String(length=50), nullable=False),
        sa.Column("name", sa.String(length=50), nullable=False),
        sa.Column("added_by", sa.String(length=50), nullable=False),
        sa.Column("added_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["event.id"],
            name=op.f("fk_event_organizer_event_id_event"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint(
            "event_id", "discord_id", name=op.f("pk_event_organizer")
        ),
    )
    op.create_index(
        op.f("ix_event_organizer_discord_id"), "event_organizer", ["discord_id"]
    )
    op.add_column("event", sa.Column("entrant_min", sa.Integer(), nullable=True))
    op.add_column(
        "event", sa.Column("cancelled_at", sa.DateTime(timezone=True), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("event", "cancelled_at")
    op.drop_column("event", "entrant_min")
    op.drop_index(op.f("ix_event_organizer_discord_id"), table_name="event_organizer")
    op.drop_table("event_organizer")
    op.drop_table("organizer_request")
    op.drop_table("organizer_grant")
