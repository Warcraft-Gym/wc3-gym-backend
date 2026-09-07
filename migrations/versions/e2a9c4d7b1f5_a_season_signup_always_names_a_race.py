"""A season signup always names a race.

Revision ID: e2a9c4d7b1f5
Revises: c3f7a1d9e408
Create Date: 2026-09-08

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "e2a9c4d7b1f5"
down_revision: str | Sequence[str] | None = "c3f7a1d9e408"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

RACE = sa.Enum("RANDOM", "HU", "OC", "NE", "UD", name="race")


def upgrade() -> None:
    # A row without a race stops the build; set it with PUT /seasons/{id}/signups/{user_id} first
    missing = (
        op.get_bind()
        .execute(
            sa.text(
                "SELECT user_id, season_id FROM user_season_signup WHERE race IS NULL"
            )
        )
        .all()
    )
    if missing:
        raise RuntimeError(f"signups without a race (user_id, season_id): {missing}")
    with op.batch_alter_table("user_season_signup") as batch:
        batch.alter_column("race", existing_type=RACE, nullable=False)


def downgrade() -> None:
    with op.batch_alter_table("user_season_signup") as batch:
        batch.alter_column("race", existing_type=RACE, nullable=True)
