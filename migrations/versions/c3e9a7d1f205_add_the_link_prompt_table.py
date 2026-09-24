"""Add the link prompt table

A suggestion that an earlier player is a login, and the notice that another
login verified a tag and took it.

Revision ID: c3e9a7d1f205
Revises: b8d4f2a6c913
Create Date: 2026-09-24 18:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c3e9a7d1f205"
down_revision: str | Sequence[str] | None = "b8d4f2a6c913"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "link_prompt",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(length=10), nullable=False),
        sa.Column("person_id", sa.Integer(), nullable=True),
        sa.Column("user_id", sa.Integer(), nullable=True),
        sa.Column("tag", sa.String(length=50), nullable=True),
        sa.Column("reason", sa.String(length=10), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("closed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("outcome", sa.String(length=10), nullable=True),
        sa.ForeignKeyConstraint(["person_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_link_prompt_person_id", "link_prompt", ["person_id"])
    op.create_index("ix_link_prompt_user_id", "link_prompt", ["user_id"])


def downgrade() -> None:
    op.drop_table("link_prompt")
