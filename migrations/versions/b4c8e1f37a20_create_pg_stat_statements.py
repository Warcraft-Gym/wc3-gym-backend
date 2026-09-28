"""Create pg_stat_statements where it is missing, so the egress snapshot reads staging too.

Supabase creates the extension in each project's postgres database; the staging app runs on
wc3gym_staging, which lacks it. A Postgres without the contrib module is left as it is.

Revision ID: b4c8e1f37a20
Revises: 5b2e9d7c4a10
Create Date: 2026-09-28 12:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b4c8e1f37a20"
down_revision: str | Sequence[str] | None = "5b2e9d7c4a10"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    op.execute(
        "DO $$ BEGIN "
        "IF EXISTS (SELECT 1 FROM pg_available_extensions WHERE name = 'pg_stat_statements') "
        "THEN CREATE EXTENSION IF NOT EXISTS pg_stat_statements; END IF; END $$"
    )


def downgrade() -> None:
    # The extension outlives this revision: prod had it before and the monitor reads it
    pass
