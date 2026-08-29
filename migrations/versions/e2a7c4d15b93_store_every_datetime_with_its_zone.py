"""Store every datetime with its zone

The columns held UTC without saying so; timestamptz says so, and a zoned
value written to it converts itself instead of trusting the session zone.

Revision ID: e2a7c4d15b93
Revises: d1f6b3e94a02
Create Date: 2026-08-29 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e2a7c4d15b93"
down_revision: str | None = "d1f6b3e94a02"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COLUMNS = [
    ("series", "date_time"),
    ("draft_series", "date_time"),
    ("draft_series", "created_at"),
    ("koth_events", "event_date"),
    ("users", "w3c_synced_at"),
    ("users", "ladder_synced_at"),
    ("w3c_ladder_matches", "start_time"),
    ("ladder_sync", "synced_at"),
]


def _retype(timezone: bool) -> None:
    kind = sa.DateTime(timezone=timezone)
    if op.get_bind().dialect.name != "postgresql":
        # SQLite keeps no zone; only created_at was declared TIMESTAMP
        with op.batch_alter_table("draft_series") as batch:
            batch.alter_column("created_at", type_=kind)
        return
    for table, column in COLUMNS:
        op.alter_column(
            table, column, type_=kind, postgresql_using=f"{column} AT TIME ZONE 'UTC'"
        )


def upgrade() -> None:
    _retype(timezone=True)


def downgrade() -> None:
    _retype(timezone=False)
