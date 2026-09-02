"""Keep a map picture in the blob store

An uploaded picture goes to Vercel Blob and `maps.image` holds its URL, the way a team logo already
works. The bytes column is dropped: it is empty in production and would bill the same egress the
team logos did. `image` grows to fit a blob URL, which carries a random suffix.

Revision ID: b1e7d4c92f38
Revises: f3c8d2a7b9e1
Create Date: 2026-09-03 01:20:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b1e7d4c92f38"
down_revision: str | Sequence[str] | None = "f3c8d2a7b9e1"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


SHORTNAME_KEY = "CREATE UNIQUE INDEX uq_maps_shortname ON maps (lower(trim(shortname)))"


def _resize(length: int, was: int) -> None:
    # batch mode: SQLite rewrites the table, which is how it changes a declared length at all
    with op.batch_alter_table("maps") as batch:
        batch.alter_column(
            "image",
            type_=sa.String(length),
            existing_type=sa.String(was),
            existing_nullable=True,
        )
    if op.get_bind().dialect.name == "sqlite":
        # the rewrite copies the indexes SQLAlchemy can reflect, and an expression index is not
        # one of them, so the unique short name goes back by hand
        op.execute(SHORTNAME_KEY)


def upgrade() -> None:
    op.drop_column("maps", "icon")
    _resize(500, 100)


def downgrade() -> None:
    _resize(100, 500)
    op.add_column("maps", sa.Column("icon", sa.LargeBinary(), nullable=True))
