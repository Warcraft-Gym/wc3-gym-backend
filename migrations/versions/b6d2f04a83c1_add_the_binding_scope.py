"""Add the binding scope

Which seasons a binding reads used to be hidden in whether it named a season.
The scope column says it: the current season, the season it names, or every
one. A binding that names a season becomes a season binding.

Revision ID: b6d2f04a83c1
Revises: a1c7f4b09d36
Create Date: 2026-09-03 13:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b6d2f04a83c1"
down_revision: str | Sequence[str] | None = "a1c7f4b09d36"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

SCOPES = ("current", "season", "all")

scope = sa.Enum(*SCOPES, name="rolescope")


def upgrade() -> None:
    # Postgres needs the type before the column; SQLite has nothing to create
    scope.create(op.get_bind(), checkfirst=True)
    with op.batch_alter_table("discord_role_binding") as batch:
        batch.add_column(
            sa.Column("scope", scope, nullable=False, server_default="current")
        )
    op.execute(
        "UPDATE discord_role_binding SET scope = 'season' WHERE season_id IS NOT NULL"
    )


def downgrade() -> None:
    with op.batch_alter_table("discord_role_binding") as batch:
        batch.drop_column("scope")
    scope.drop(op.get_bind(), checkfirst=True)
