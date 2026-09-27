"""Index ladder matches by user, race and start time

Revision ID: 5b2e9d7c4a10
Revises: 14261ed1246f
Create Date: 2026-09-26 18:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "5b2e9d7c4a10"
down_revision: str | Sequence[str] | None = "14261ed1246f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_w3c_ladder_matches_user_id_race_start_time",
        "w3c_ladder_matches",
        ["user_id", "race", "start_time"],
    )


def downgrade() -> None:
    op.drop_index("ix_w3c_ladder_matches_user_id_race_start_time", "w3c_ladder_matches")
