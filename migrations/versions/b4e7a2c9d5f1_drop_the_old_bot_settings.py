"""Drop the settings rows only the old Discord bot read

The captain/coach and admin role ids and the signup, player profile, fantasy
dashboard and scheduling channel ids served a bot that no longer runs. Nothing
reads them: admins come from admin_grant and ADMIN_DISCORD_IDS, the roles the
app owns are discord_role_binding rows, and /postlinks posts the site links in
the channel an admin names.

Revision ID: b4e7a2c9d5f1
Revises: d47305003af9
Create Date: 2026-10-22 09:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b4e7a2c9d5f1"
down_revision: str | Sequence[str] | None = "d47305003af9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

OLD_BOT_KEYS = (
    "captain_coach_role",
    "admin_role",
    "signup_channel_id",
    "dashboard_channel_id",
    "fantasy_dashboard_channel_id",
    "scheduling_channel_id",
)


def upgrade() -> None:
    keys = ", ".join(f"'{key}'" for key in OLD_BOT_KEYS)
    op.execute(f"DELETE FROM settings WHERE key IN ({keys})")


def downgrade() -> None:
    # The values are gone and nothing read them, so there is nothing to put back
    pass
