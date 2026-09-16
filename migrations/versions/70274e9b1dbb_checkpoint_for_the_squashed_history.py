"""Checkpoint for the squashed history

A no-op revision. Every persistent database is moved to it before the older
revisions are rewritten into one baseline that keeps this revision id, so a
database already here runs no DDL and an empty database builds the schema in
one step.

Revision ID: 70274e9b1dbb
Revises: e6b3a19d4f72
Create Date: 2026-09-16 18:00:00.000000

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "70274e9b1dbb"
down_revision: str | Sequence[str] | None = "e6b3a19d4f72"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    pass


def downgrade() -> None:
    pass
