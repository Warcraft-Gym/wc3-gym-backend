"""Drop the users battle tag column

user_battle_tag holds every real tag, and User.battleTag reads the active
row. The column held a copy of it, and a stand-in tag the importers wrote
where a sheet had no tag; an importer now finds such a person by name.

Revision ID: b8d4f2a6c913
Revises: e07324d2b4f9
Create Date: 2026-09-24 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b8d4f2a6c913"
down_revision: str | Sequence[str] | None = "e07324d2b4f9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index("uq_users_battle_tag", table_name="users")
    op.drop_column("users", "battleTag")


def downgrade() -> None:
    # The column comes back nullable and refilled from the active tag row. The
    # old stand-ins are gone: a person with no tag gets Review#<id>, a stand-in
    # the code before this revision reads as no tag and its downgrade accepts
    op.add_column(
        "users",
        sa.Column(
            "battleTag", sqlmodel.sql.sqltypes.AutoString(length=50), nullable=True
        ),
    )
    op.execute(
        'UPDATE users SET "battleTag" = (SELECT t.tag FROM user_battle_tag t '
        "WHERE t.user_id = users.id AND t.is_active)"
    )
    op.execute(
        'UPDATE users SET "battleTag" = \'Review#\' || id WHERE "battleTag" IS NULL'
    )
    op.execute(
        'CREATE UNIQUE INDEX uq_users_battle_tag ON users (lower(trim("battleTag")))'
    )
