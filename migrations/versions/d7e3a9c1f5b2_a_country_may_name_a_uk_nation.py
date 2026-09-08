"""A country may name a UK nation

The users country grows from two letters to six so it can hold GB-SCT, the
code w3champions and flagpack both use for Scotland.

Revision ID: d7e3a9c1f5b2
Revises: b4c8e1f6a2d9
Create Date: 2026-09-08 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d7e3a9c1f5b2"
down_revision: str | Sequence[str] | None = "b4c8e1f6a2d9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


# The expression keys of users, as f7a2c95e3b18 and c5d9e2f47a81 built them
KEYS = (
    'CREATE UNIQUE INDEX uq_users_battle_tag ON users (lower(trim("battleTag")))',
    (
        'CREATE UNIQUE INDEX uq_users_discord_tag ON users (lower(trim("discordTag")))'
        " WHERE trim(\"discordTag\") <> ''"
    ),
    (
        'CREATE UNIQUE INDEX uq_users_discord_id ON users (trim("discordId"))'
        " WHERE trim(\"discordId\") <> ''"
    ),
)


def _resize(length: int, was: int) -> None:
    # batch mode: SQLite rewrites the table, which is how it changes a declared length at all
    with op.batch_alter_table("users") as batch:
        batch.alter_column(
            "country",
            type_=sa.String(length),
            existing_type=sa.String(was),
            existing_nullable=True,
        )
    if op.get_bind().dialect.name == "sqlite":
        # the rewrite copies the indexes SQLAlchemy can reflect, and an expression index is not
        # one of them, so the three keys go back by hand
        for key in KEYS:
            op.execute(key)


def upgrade() -> None:
    _resize(6, 2)


def downgrade() -> None:
    _resize(2, 6)
