"""Add the Discord id key of a player

A Clerk session names its player by Discord id (`clerk_account.discord_id`
to `users."discordId"`), so two rows with one id would make the login pick
one at random. An import writes a blank id for a player who has none, and
blank means unknown, so the index skips it, as the Discord tag key does.

Revision ID: c5d9e2f47a81
Revises: a4d2e8f19c37
Create Date: 2026-08-30 18:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c5d9e2f47a81"
down_revision: str | Sequence[str] | None = "a4d2e8f19c37"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        'CREATE UNIQUE INDEX uq_users_discord_id ON users (trim("discordId"))'
        " WHERE trim(\"discordId\") <> ''"
    )


def downgrade() -> None:
    op.drop_index("uq_users_discord_id", table_name="users")
