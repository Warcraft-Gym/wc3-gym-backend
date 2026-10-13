"""Add the recurring cups

A cup can repeat on a rule: a weekday, every week or the nth of the month, at
a local start time. `cup_recurrence` holds the rule and `cup_occurrence` the
cups made from it, one per day. No existing cup repeats, so nothing is
filled.

Revision ID: e5c1a9d7b246
Revises: d3b8f1a6c925
Create Date: 2026-10-13 20:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e5c1a9d7b246"
down_revision: str | Sequence[str] | None = "d3b8f1a6c925"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "cup_recurrence",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=80), nullable=False),
        sa.Column("weekday", sa.Integer(), nullable=False),
        sa.Column("nth", sa.Integer(), nullable=True),
        sa.Column("start_time", sa.String(length=5), nullable=False),
        sa.Column("zone", sa.String(length=64), nullable=False),
        sa.Column("starts_on", sa.Date(), nullable=False),
        sa.Column("ends_on", sa.Date(), nullable=True),
        sa.Column("created_by", sa.String(length=50), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_cup_recurrence")),
    )
    op.create_table(
        "cup_occurrence",
        sa.Column("event_id", sa.Integer(), nullable=False),
        sa.Column("recurrence_id", sa.Integer(), nullable=False),
        sa.Column("occurs_on", sa.Date(), nullable=False),
        sa.ForeignKeyConstraint(
            ["event_id"],
            ["event.id"],
            name=op.f("fk_cup_occurrence_event_id_event"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["recurrence_id"],
            ["cup_recurrence.id"],
            name=op.f("fk_cup_occurrence_recurrence_id_cup_recurrence"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("event_id", name=op.f("pk_cup_occurrence")),
        sa.UniqueConstraint(
            "recurrence_id", "occurs_on", name=op.f("uq_cup_occurrence_recurrence_id")
        ),
    )
    op.create_index(
        op.f("ix_cup_occurrence_recurrence_id"),
        "cup_occurrence",
        ["recurrence_id"],
        unique=False,
    )


def downgrade() -> None:
    # The cups made from a rule stay; they read as cups of their own
    op.drop_index(op.f("ix_cup_occurrence_recurrence_id"), table_name="cup_occurrence")
    op.drop_table("cup_occurrence")
    op.drop_table("cup_recurrence")
