"""Add the user block and user busy tables

A player can say when they cannot play: a repeating block of local hours on
some weekdays, or a run of whole local days. Both are soft hints for the
scheduling tools and belong to the player, not to an event. The models read
them in a later PR, after this migration has run.

Revision ID: 75b9f3b280c2
Revises: 160f8f7bf2d4
Create Date: 2026-09-11 23:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "75b9f3b280c2"
down_revision: str | Sequence[str] | None = "160f8f7bf2d4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> list[sa.Column]:
    return [
        sa.Column(
            name,
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        )
        for name in ("created_at", "updated_at")
    ]


def upgrade() -> None:
    op.create_table(
        "user_block",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(length=40), nullable=True),
        # ISO weekday bits: Monday = 1, Tuesday = 2, ... Sunday = 64
        sa.Column("weekdays", sa.SmallInteger(), nullable=False),
        # Wall-clock time in users.timezone; an end before the start runs past midnight
        sa.Column("start_local", sa.Time(), nullable=False),
        sa.Column("end_local", sa.Time(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "weekdays BETWEEN 1 AND 127", name=op.f("ck_user_block_weekdays")
        ),
        sa.CheckConstraint(
            "end_local <> start_local", name=op.f("ck_user_block_not_empty")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_user_block_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_block")),
    )
    op.create_index(op.f("ix_user_block_user_id"), "user_block", ["user_id"])

    op.create_table(
        "user_busy",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(length=40), nullable=True),
        # Whole local days in users.timezone, both ends included
        sa.Column("first_day", sa.Date(), nullable=False),
        sa.Column("last_day", sa.Date(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "last_day >= first_day", name=op.f("ck_user_busy_day_order")
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name=op.f("fk_user_busy_user_id_users"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_user_busy")),
    )
    # A read skips the ranges that ended before the round
    op.create_index(
        op.f("ix_user_busy_user_id_last_day"), "user_busy", ["user_id", "last_day"]
    )


def downgrade() -> None:
    op.drop_table("user_busy")
    op.drop_table("user_block")
