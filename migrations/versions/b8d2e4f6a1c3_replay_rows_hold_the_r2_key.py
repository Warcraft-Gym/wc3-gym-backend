"""The replay row holds its R2 object key, not a Vercel Blob URL.

Revision ID: b8d2e4f6a1c3
Revises: a3f7c2d9e5b1
Create Date: 2026-09-05

"""

from collections.abc import Sequence

from alembic import op

revision: str = "b8d2e4f6a1c3"
down_revision: str | Sequence[str] | None = "a3f7c2d9e5b1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # every existing row points at Vercel Blob, which the app no longer reads
    op.execute("DELETE FROM series_replay")
    op.alter_column("series_replay", "url", new_column_name="key")


def downgrade() -> None:
    op.execute("DELETE FROM series_replay")
    op.alter_column("series_replay", "key", new_column_name="url")
