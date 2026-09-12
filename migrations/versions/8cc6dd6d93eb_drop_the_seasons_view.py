"""Drop the seasons view

The second of the four deploys of the events model. B1 renamed the table to
`event` and left an updatable `seasons` view behind so the deploy that was
still running could read the old name. That deploy is gone by now, so the
view goes; the downgrade puts it back.

Revision ID: 8cc6dd6d93eb
Revises: 1e0287eacccf
Create Date: 2026-09-12 04:22:56.777848

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "8cc6dd6d93eb"
down_revision: str | Sequence[str] | None = "1e0287eacccf"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("DROP VIEW seasons")


def downgrade() -> None:
    op.execute("CREATE VIEW seasons AS SELECT * FROM event")
