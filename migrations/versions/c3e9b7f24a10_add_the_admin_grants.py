"""Add the admin grants

Discord decided who administered the site, so the guild owned the app's rights.
A grant row does now, with ADMIN_DISCORD_IDS as the bootstrap, and the rolekind
enum gains admin so a binding can mirror the grant back to the guild.

Revision ID: c3e9b7f24a10
Revises: e7b4d0a35c19
Create Date: 2026-08-30 17:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
import sqlmodel
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c3e9b7f24a10"
down_revision: str | Sequence[str] | None = "e7b4d0a35c19"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "admin_grant",
        sa.Column(
            "discord_id", sqlmodel.sql.sqltypes.AutoString(length=50), nullable=False
        ),
        sa.Column("name", sqlmodel.sql.sqltypes.AutoString(length=50), nullable=False),
        sa.Column(
            "granted_by", sqlmodel.sql.sqltypes.AutoString(length=50), nullable=False
        ),
        sa.Column("granted_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("discord_id", name=op.f("pk_admin_grant")),
    )
    if op.get_bind().dialect.name == "postgresql":
        # Postgres alone holds the enum labels; the other dialects store the string
        op.execute("ALTER TYPE rolekind ADD VALUE IF NOT EXISTS 'admin'")


def downgrade() -> None:
    # Postgres cannot drop an enum label, so admin stays in rolekind
    op.drop_table("admin_grant")
